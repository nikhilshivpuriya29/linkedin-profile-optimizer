"""Unit tests for HuggingFaceClient retry and fallback logic.

Requirements: 9.1, 9.3, 9.4, 9.5, 9.6
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from linkedin_optimizer.integrations.hf_client import (
    HuggingFaceClient,
    HFResponse,
    HFTimeoutError,
    HFAPIError,
)
from linkedin_optimizer.config import HFModelConfig


@pytest.fixture
def hf_config() -> HFModelConfig:
    """Create a test HFModelConfig with short timeouts."""
    return HFModelConfig(
        model_id="primary-model/test",
        fallback_model_id="fallback-model/test",
        api_token="test-token-123",
        timeout_seconds=30,
        max_retries=3,
        backoff_base_seconds=2,
    )


@pytest.fixture
def client(hf_config: HFModelConfig) -> HuggingFaceClient:
    """Create a HuggingFaceClient instance for testing."""
    return HuggingFaceClient(hf_config)


def _mock_response(status_code: int = 200, json_data=None, text: str = "") -> httpx.Response:
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_data if json_data is not None else []
    response.text = text
    return response


class TestSuccessfulGeneration:
    """Test successful text generation with mocked HTTP responses."""

    async def test_successful_generation_returns_hf_response(self, client: HuggingFaceClient):
        """Req 9.1: Successful generation returns proper HFResponse."""
        mock_response = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Optimized headline for your profile"}],
        )

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.generate("Optimize my headline")

        assert isinstance(result, HFResponse)
        assert result.text == "Optimized headline for your profile"
        assert result.model_used == "primary-model/test"
        assert result.is_fallback is False
        assert result.tokens_used > 0

    async def test_successful_generation_uses_primary_model(self, client: HuggingFaceClient):
        """Req 9.1: Successful call uses the primary model endpoint."""
        mock_response = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Result text"}],
        )

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await client.generate("Test prompt")

        # Verify the URL contains the primary model
        call_url = mock_post.call_args[0][0]
        assert "primary-model/test" in call_url


class TestRetryBehavior:
    """Test retry behavior with transient failures (Req 9.3, 9.4)."""

    async def test_retry_on_transient_503_then_success(self, client: HuggingFaceClient):
        """Req 9.4: First call returns 503, second succeeds after retry."""
        error_response = _mock_response(status_code=503, text="Service Unavailable")
        success_response = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Success after retry"}],
        )

        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=[error_response, success_response],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.generate("Test prompt")

        assert result.text == "Success after retry"
        assert result.is_fallback is False

    async def test_retry_uses_exponential_backoff(self, client: HuggingFaceClient):
        """Req 9.4: Retries use exponential backoff (2s, 4s, 8s)."""
        error_response = _mock_response(status_code=503, text="Service Unavailable")
        success_response = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Eventually succeeded"}],
        )

        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=[error_response, error_response, success_response],
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result = await client.generate("Test prompt")

        # Verify backoff delays: 2s (2*2^0), 4s (2*2^1)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)  # First retry delay
        mock_sleep.assert_any_call(4)  # Second retry delay

        assert result.text == "Eventually succeeded"


class TestFallbackActivation:
    """Test fallback model activation on non-timeout errors (Req 9.3, 9.5)."""

    async def test_fallback_activates_after_all_retries_fail(self, client: HuggingFaceClient):
        """Req 9.3: All retries fail on primary → fallback model succeeds."""
        error_response = _mock_response(status_code=503, text="Service Unavailable")
        fallback_success = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Fallback result"}],
        )

        # 3 failures on primary (max_retries=3), then success on fallback
        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=[error_response, error_response, error_response, fallback_success],
        ) as mock_post:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await client.generate("Test prompt")

        assert result.text == "Fallback result"
        assert result.is_fallback is True
        assert result.model_used == "fallback-model/test"

        # Verify fallback URL was called
        last_call_url = mock_post.call_args_list[-1][0][0]
        assert "fallback-model/test" in last_call_url


class TestTimeoutCancellation:
    """Test timeout behavior: no fallback for timeouts (Req 9.5)."""

    async def test_timeout_raises_hf_timeout_error(self, client: HuggingFaceClient):
        """Req 9.5: Timeout raises HFTimeoutError immediately."""
        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Request timed out"),
        ):
            with pytest.raises(HFTimeoutError):
                await client.generate("Test prompt")

    async def test_timeout_does_not_trigger_fallback(self, client: HuggingFaceClient):
        """Req 9.5: Timeout does NOT attempt fallback model."""
        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Request timed out"),
        ) as mock_post:
            with pytest.raises(HFTimeoutError):
                await client.generate("Test prompt")

        # Only one call should be made (no fallback attempt)
        assert mock_post.call_count == 1

    async def test_timeout_does_not_retry(self, client: HuggingFaceClient):
        """Req 9.5: Timeout is NOT retried — it raises immediately."""
        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Request timed out"),
        ) as mock_post:
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                with pytest.raises(HFTimeoutError):
                    await client.generate("Test prompt")

        # No retries or fallback
        assert mock_post.call_count == 1
        mock_sleep.assert_not_called()


class TestConversationContext:
    """Test conversation context accumulation (Req 9.6)."""

    async def test_context_accumulates_after_successful_calls(self, client: HuggingFaceClient):
        """Req 9.6: Two successful calls accumulate conversation context."""
        response_1 = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "First response"}],
        )
        response_2 = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Second response"}],
        )

        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=[response_1, response_2],
        ):
            await client.generate("First prompt")
            await client.generate("Second prompt")

        context = client.conversation_context
        assert len(context) == 4  # 2 user + 2 assistant entries
        assert context[0] == {"role": "user", "content": "First prompt"}
        assert context[1] == {"role": "assistant", "content": "First response"}
        assert context[2] == {"role": "user", "content": "Second prompt"}
        assert context[3] == {"role": "assistant", "content": "Second response"}

    async def test_clear_context_resets_conversation(self, client: HuggingFaceClient):
        """Req 9.6: clear_context() resets conversation history."""
        mock_response = _mock_response(
            status_code=200,
            json_data=[{"generated_text": "Some response"}],
        )

        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=mock_response):
            await client.generate("A prompt")

        assert len(client.conversation_context) == 2

        client.clear_context()

        assert len(client.conversation_context) == 0

    async def test_context_not_accumulated_on_failure(self, client: HuggingFaceClient):
        """Req 9.6: Failed calls do not add to conversation context."""
        with patch.object(
            client._client, "post", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Timed out"),
        ):
            with pytest.raises(HFTimeoutError):
                await client.generate("Failing prompt")

        assert len(client.conversation_context) == 0
