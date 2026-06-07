"""Property-based tests for HuggingFace client retry and fallback logic.

**Validates: Requirements 1.5, 9.3, 9.4, 9.5**

These tests use Hypothesis to verify:
- Property 4: Retry logic respects attempt limits and backoff timing
- Property 24: Model fallback on timeout behavior
"""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.config import HFModelConfig
from linkedin_optimizer.integrations.hf_client import (
    HFAPIError,
    HFTimeoutError,
    HuggingFaceClient,
)


# --- Helpers ---


def make_config(
    max_retries: int = 3,
    backoff_base_seconds: int = 2,
    timeout_seconds: int = 30,
) -> HFModelConfig:
    """Create an HFModelConfig for testing."""
    return HFModelConfig(
        model_id="test/primary-model",
        fallback_model_id="test/fallback-model",
        api_token="test-token",
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        backoff_base_seconds=backoff_base_seconds,
    )


# =============================================================================
# Property 4: Retry logic respects attempt limits and backoff timing
# =============================================================================


@pytest.mark.property
class TestProperty4RetryLogic:
    """Property 4: Retry logic respects attempt limits and backoff timing.

    **Validates: Requirements 1.5, 9.3, 9.4**

    For any sequence of N consecutive failures from HuggingFace API:
    - If N <= max_retries, the system retries with exponential backoff
    - Retry count never exceeds max_retries
    - Backoff delays double from base (2s, 4s, 8s, ...)
    """

    @given(
        num_failures=st.integers(min_value=1, max_value=6),
        max_retries=st.integers(min_value=1, max_value=5),
        backoff_base=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_retry_count_never_exceeds_max_retries(
        self, num_failures: int, max_retries: int, backoff_base: int
    ):
        """Retry count is always ≤ max_retries regardless of failures."""
        config = make_config(
            max_retries=max_retries, backoff_base_seconds=backoff_base
        )
        client = HuggingFaceClient(config)

        call_count = 0

        async def mock_call_model(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= num_failures:
                raise HFAPIError(
                    f"Simulated failure #{call_count}", status_code=503
                )
            # Success after failures
            from linkedin_optimizer.integrations.hf_client import HFResponse

            return HFResponse(
                text="success", model_used="test/primary-model", tokens_used=10
            )

        async def run():
            nonlocal call_count
            call_count = 0
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    try:
                        await client._retry_with_backoff(
                            model_id=config.model_id,
                            prompt="test prompt",
                        )
                    except HFAPIError:
                        pass  # Expected when all retries exhausted

            # The total calls should never exceed max_retries
            assert call_count <= max_retries

        asyncio.run(run())

    @given(
        max_retries=st.integers(min_value=2, max_value=5),
        backoff_base=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_backoff_delays_double_from_base(
        self, max_retries: int, backoff_base: int
    ):
        """Backoff delays follow exponential pattern: base * 2^attempt."""
        config = make_config(
            max_retries=max_retries, backoff_base_seconds=backoff_base
        )
        client = HuggingFaceClient(config)

        recorded_delays: list[float] = []

        async def mock_sleep(delay):
            recorded_delays.append(delay)

        async def mock_call_model(*args, **kwargs):
            raise HFAPIError("Always fails", status_code=503)

        async def run():
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", side_effect=mock_sleep):
                    try:
                        await client._retry_with_backoff(
                            model_id=config.model_id,
                            prompt="test prompt",
                        )
                    except HFAPIError:
                        pass

            # Should have (max_retries - 1) delays (sleep between retries)
            assert len(recorded_delays) == max_retries - 1

            # Each delay should be base * 2^attempt_index
            for i, delay in enumerate(recorded_delays):
                expected_delay = backoff_base * (2**i)
                assert delay == expected_delay, (
                    f"Delay at attempt {i} was {delay}, "
                    f"expected {expected_delay} (base={backoff_base})"
                )

        asyncio.run(run())

    @given(
        num_failures=st.integers(min_value=1, max_value=10),
        max_retries=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100)
    def test_all_retries_exhausted_raises_last_error(
        self, num_failures: int, max_retries: int
    ):
        """When all retries are exhausted, the last error is raised."""
        assume(num_failures >= max_retries)

        config = make_config(max_retries=max_retries)
        client = HuggingFaceClient(config)

        call_count = 0

        async def mock_call_model(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise HFAPIError(
                f"Failure #{call_count}", status_code=503
            )

        async def run():
            nonlocal call_count
            call_count = 0
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(HFAPIError) as exc_info:
                        await client._retry_with_backoff(
                            model_id=config.model_id,
                            prompt="test prompt",
                        )
                    # The raised error should be from the last attempt
                    assert f"Failure #{max_retries}" in str(exc_info.value)

            # Exactly max_retries calls should have been made
            assert call_count == max_retries

        asyncio.run(run())


# =============================================================================
# Property 24: Model fallback on timeout
# =============================================================================


@pytest.mark.property
class TestProperty24ModelFallbackOnTimeout:
    """Property 24: Model fallback on timeout.

    **Validates: Requirements 9.3, 9.5**

    - Timeout → raises HFTimeoutError without attempting fallback
    - Non-timeout errors after retries → attempts fallback model
    """

    @given(
        max_retries=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=100)
    def test_timeout_raises_immediately_no_fallback(self, max_retries: int):
        """Timeout causes immediate raise without fallback attempt."""
        config = make_config(max_retries=max_retries)
        client = HuggingFaceClient(config)

        models_called: list[str] = []

        async def mock_call_model(model_id, *args, **kwargs):
            models_called.append(model_id)
            raise HFTimeoutError(f"Timeout calling {model_id}")

        async def run():
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(HFTimeoutError):
                        await client.generate(prompt="test prompt")

            # Only the primary model should have been called (no fallback)
            assert all(
                m == config.model_id for m in models_called
            ), f"Fallback was attempted: {models_called}"
            # Timeout should not retry - only 1 call
            assert len(models_called) == 1

        asyncio.run(run())

    @given(
        max_retries=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_non_timeout_errors_trigger_fallback(self, max_retries: int):
        """Non-timeout errors after exhausted retries attempt fallback."""
        config = make_config(max_retries=max_retries)
        client = HuggingFaceClient(config)

        models_called: list[str] = []

        async def mock_call_model(model_id, *args, **kwargs):
            models_called.append(model_id)
            if model_id == config.model_id:
                raise HFAPIError("Service unavailable", status_code=503)
            # Fallback model succeeds
            from linkedin_optimizer.integrations.hf_client import HFResponse

            return HFResponse(
                text="fallback response",
                model_used=config.fallback_model_id,
                tokens_used=5,
            )

        async def run():
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    response = await client.generate(prompt="test prompt")

            # Primary model should have been tried max_retries times
            primary_calls = [
                m for m in models_called if m == config.model_id
            ]
            assert len(primary_calls) == max_retries

            # Fallback model should have been attempted
            fallback_calls = [
                m for m in models_called if m == config.fallback_model_id
            ]
            assert len(fallback_calls) >= 1

            # Response should be marked as fallback
            assert response.is_fallback is True
            assert response.model_used == config.fallback_model_id

        asyncio.run(run())

    @given(
        max_retries=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_timeout_on_first_call_no_retry(self, max_retries: int):
        """Timeout on the very first attempt should not trigger retries."""
        config = make_config(max_retries=max_retries)
        client = HuggingFaceClient(config)

        call_count = 0

        async def mock_call_model(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise HFTimeoutError("Immediate timeout")

        async def run():
            nonlocal call_count
            call_count = 0
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(HFTimeoutError):
                        await client._retry_with_backoff(
                            model_id=config.model_id,
                            prompt="test prompt",
                        )

            # Timeout should immediately raise - only 1 attempt, no retries
            assert call_count == 1

        asyncio.run(run())

    @given(
        max_retries=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=100)
    def test_fallback_failure_raises_error(self, max_retries: int):
        """When both primary and fallback fail with non-timeout errors, raises."""
        config = make_config(max_retries=max_retries)
        client = HuggingFaceClient(config)

        async def mock_call_model(model_id, *args, **kwargs):
            raise HFAPIError(f"Failed: {model_id}", status_code=503)

        async def run():
            with patch.object(client, "_call_model", side_effect=mock_call_model):
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(HFAPIError) as exc_info:
                        await client.generate(prompt="test prompt")

                    # The error should reference the fallback model
                    assert config.fallback_model_id in str(exc_info.value)

        asyncio.run(run())
