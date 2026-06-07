"""Hugging Face Inference API client with retry and fallback logic."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from linkedin_optimizer.config import HFModelConfig

logger = logging.getLogger(__name__)


@dataclass
class HFResponse:
    """Response from Hugging Face model generation."""

    text: str
    model_used: str
    tokens_used: int
    is_fallback: bool = False


class HFTimeoutError(Exception):
    """Raised when a HF API request exceeds the configured timeout."""

    pass


class HFAPIError(Exception):
    """Raised for non-timeout HF API errors (service down, model not found, etc.)."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class HuggingFaceClient:
    """Adapter for Hugging Face Inference API with retry and fallback.

    Implements:
    - 30-second timeout per request (Req 9.5)
    - Exponential backoff retry: 2s, 4s, 8s up to 3 attempts (Req 9.4)
    - Fallback model for non-timeout errors only (Req 9.5, 9.7)
    - Conversation context for consistent tone across sections (Req 9.6)
    """

    BASE_URL = "https://api-inference.huggingface.co/models"

    def __init__(self, config: HFModelConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
            headers={
                "Authorization": f"Bearer {config.api_token}",
                "Content-Type": "application/json",
            },
        )
        self._conversation_context: list[dict[str, str]] = []

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "HuggingFaceClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    @property
    def conversation_context(self) -> list[dict[str, str]]:
        """Access the conversation context for inspection."""
        return self._conversation_context

    def clear_context(self) -> None:
        """Clear conversation context (e.g., between pipeline runs)."""
        self._conversation_context = []

    async def generate(
        self,
        prompt: str,
        system_context: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> HFResponse:
        """Generate text with retry and fallback logic.

        Flow:
        1. Try primary model with retry+backoff
        2. On timeout → raise immediately (no fallback per Req 9.5)
        3. On non-timeout errors after retries exhausted → try fallback model
        4. On fallback success → return with is_fallback=True
        5. On fallback failure → raise the error

        Args:
            prompt: The user prompt for generation.
            system_context: Optional system-level context for the model.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            HFResponse with generated text and metadata.

        Raises:
            HFTimeoutError: If request times out (no fallback attempted).
            HFAPIError: If both primary and fallback models fail.
        """
        try:
            response = await self._retry_with_backoff(
                model_id=self.config.model_id,
                prompt=prompt,
                system_context=system_context,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            # Store successful interaction in conversation context
            self._conversation_context.append(
                {"role": "user", "content": prompt}
            )
            self._conversation_context.append(
                {"role": "assistant", "content": response.text}
            )
            return response
        except HFTimeoutError:
            # Timeout → cancel without fallback (Req 9.5)
            logger.warning(
                "Request to model '%s' timed out. Not attempting fallback.",
                self.config.model_id,
            )
            raise
        except HFAPIError as e:
            # Non-timeout error → attempt fallback model (Req 9.7)
            if not self._should_use_fallback(e):
                raise

            logger.info(
                "Primary model '%s' failed with non-timeout error. "
                "Attempting fallback model '%s'.",
                self.config.model_id,
                self.config.fallback_model_id,
            )
            try:
                response = await self._retry_with_backoff(
                    model_id=self.config.fallback_model_id,
                    prompt=prompt,
                    system_context=system_context,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                response.is_fallback = True
                # Store successful interaction in conversation context
                self._conversation_context.append(
                    {"role": "user", "content": prompt}
                )
                self._conversation_context.append(
                    {"role": "assistant", "content": response.text}
                )
                return response
            except HFTimeoutError:
                logger.warning(
                    "Fallback model '%s' timed out.",
                    self.config.fallback_model_id,
                )
                raise
            except HFAPIError as fallback_error:
                logger.error(
                    "Fallback model '%s' also failed: %s",
                    self.config.fallback_model_id,
                    fallback_error,
                )
                raise

    async def _call_model(
        self,
        model_id: str,
        prompt: str,
        system_context: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> HFResponse:
        """Make a single HTTP POST to the HF Inference API.

        Args:
            model_id: The Hugging Face model identifier.
            prompt: The input prompt.
            system_context: Optional system context prepended to the prompt.
            max_tokens: Maximum new tokens to generate.
            temperature: Sampling temperature.

        Returns:
            HFResponse with the generated text.

        Raises:
            HFTimeoutError: If the request exceeds the configured timeout.
            HFAPIError: For HTTP errors or unexpected response format.
        """
        url = f"{self.BASE_URL}/{model_id}"

        # Build the full prompt including system context and conversation history
        full_prompt = self._build_full_prompt(prompt, system_context)

        payload = {
            "inputs": full_prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
            },
        }

        try:
            response = await self._client.post(url, json=payload)
        except httpx.TimeoutException as e:
            raise HFTimeoutError(
                f"Request to model '{model_id}' timed out after "
                f"{self.config.timeout_seconds}s: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise HFAPIError(
                f"HTTP error communicating with model '{model_id}': {e}"
            ) from e

        if response.status_code != 200:
            raise HFAPIError(
                f"HF API returned status {response.status_code} for model "
                f"'{model_id}': {response.text}",
                status_code=response.status_code,
            )

        # Parse the response
        try:
            data = response.json()
        except ValueError as e:
            raise HFAPIError(
                f"Invalid JSON response from model '{model_id}': {e}"
            ) from e

        generated_text = self._extract_text(data)
        tokens_used = self._extract_token_count(data, generated_text)

        return HFResponse(
            text=generated_text,
            model_used=model_id,
            tokens_used=tokens_used,
            is_fallback=False,
        )

    async def _retry_with_backoff(
        self,
        model_id: str,
        prompt: str,
        system_context: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> HFResponse:
        """Retry API calls with exponential backoff.

        Backoff schedule: 2s, 4s, 8s (base * 2^attempt)
        Max attempts: config.max_retries (default 3)

        On timeout, raises immediately without further retries.

        Args:
            model_id: The model to call.
            prompt: The input prompt.
            system_context: Optional system context.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            HFResponse on success.

        Raises:
            HFTimeoutError: Immediately on timeout (no retry).
            HFAPIError: After all retries are exhausted.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.config.max_retries):
            try:
                return await self._call_model(
                    model_id=model_id,
                    prompt=prompt,
                    system_context=system_context,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except HFTimeoutError:
                # Timeout → raise immediately, no retries (Req 9.5)
                raise
            except HFAPIError as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    delay = self.config.backoff_base_seconds * (2**attempt)
                    logger.warning(
                        "Attempt %d/%d for model '%s' failed: %s. "
                        "Retrying in %ds...",
                        attempt + 1,
                        self.config.max_retries,
                        model_id,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "All %d attempts for model '%s' exhausted.",
                        self.config.max_retries,
                        model_id,
                    )

        # All retries exhausted
        raise last_error  # type: ignore[misc]

    def _should_use_fallback(self, error: Exception) -> bool:
        """Determine if an error warrants fallback model usage.

        Returns True for non-timeout errors:
        - Service unavailable (503)
        - Model not found (404)
        - API errors (4xx/5xx)
        - Connection errors

        Returns False for timeouts (Req 9.5):
        - Request exceeded 30-second timeout → cancel without fallback
        """
        if isinstance(error, HFTimeoutError):
            return False
        # All other errors (HFAPIError, connection issues) → use fallback
        return True

    def _build_full_prompt(
        self, prompt: str, system_context: Optional[str]
    ) -> str:
        """Build the full prompt including system context and conversation history.

        This maintains conversation context across calls within a pipeline run
        for consistent tone (Req 9.6).
        """
        parts: list[str] = []

        if system_context:
            parts.append(f"[System]: {system_context}")

        # Include conversation history for context continuity
        if self._conversation_context:
            parts.append("[Conversation History]:")
            for entry in self._conversation_context:
                role = entry["role"].capitalize()
                parts.append(f"{role}: {entry['content']}")

        parts.append(f"[Current Request]: {prompt}")

        return "\n\n".join(parts)

    def _extract_text(self, data: object) -> str:
        """Extract generated text from HF API response.

        The HF Inference API can return:
        - A list of dicts with 'generated_text' key
        - A single dict with 'generated_text' key
        - A list of dicts with 'text' key (some models)
        """
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            if isinstance(item, dict):
                if "generated_text" in item:
                    return item["generated_text"]
                if "text" in item:
                    return item["text"]
        elif isinstance(data, dict):
            if "generated_text" in data:
                return data["generated_text"]
            if "text" in data:
                return data["text"]

        # Fallback: convert to string
        return str(data)

    def _extract_token_count(self, data: object, text: str) -> int:
        """Extract or estimate token count from response.

        Some models include token usage info; otherwise estimate from text length.
        """
        if isinstance(data, list) and len(data) > 0:
            item = data[0]
            if isinstance(item, dict) and "details" in item:
                details = item["details"]
                if isinstance(details, dict):
                    if "generated_tokens" in details:
                        return details["generated_tokens"]

        # Rough estimate: ~4 characters per token
        return max(1, len(text) // 4)
