"""Property-based tests for pipeline ordering and concurrency (Properties 17, 18).

**Validates: Requirements 6.3, 6.4, 6.5, 6.7**

These tests verify:
- Property 17: Pipeline stage ordering and error propagation — stages execute
  in strict order (Scraper → GitHub → Analyzer → ContentCreator → Approval),
  and if any stage fails, no subsequent stages execute. GitHub failure does NOT
  halt the pipeline (graceful degradation).
- Property 18: Run queue serialization — concurrent pipeline triggers are
  serialized so only one executes at a time via the asyncio.Lock in
  PipelineOrchestrator.
"""

import asyncio
import uuid
from datetime import datetime
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.config import PipelineConfig
from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalSession,
    ApprovalStatus,
    ContentPackage,
    ExtractionResult,
    GitHubData,
    GitHubExtractionResult,
    HeadlineSuggestion,
    OptimizationReport,
    PipelineStatus,
    ProfileData,
    RunMetadata,
    SectionScore,
)
from linkedin_optimizer.orchestrator import PipelineOrchestrator


# =============================================================================
# Test Fixtures and Helpers
# =============================================================================


def _make_config(tmp_path: str = "/tmp/test_pipeline") -> PipelineConfig:
    """Create a minimal PipelineConfig for testing."""
    return PipelineConfig(
        linkedin_profile_url="https://www.linkedin.com/in/testuser",
        github_username="testuser",
        schedule_interval=None,
        analyzer_model_id="test/model",
        content_model_id="test/model",
        fallback_model_id="test/fallback",
        data_dir=tmp_path,
        hf_api_token="test-token",
        hf_timeout_seconds=30,
        hf_max_retries=3,
    )


def _make_profile_data() -> ProfileData:
    """Create a valid ProfileData for testing."""
    return ProfileData(
        headline="Test Headline",
        about="Test about section content.",
        experience=[{"title": "Engineer", "company": "TestCo"}],
        skills=[{"name": "Python"}],
    )


def _make_extraction_result(success: bool = True) -> ExtractionResult:
    """Create a mock ExtractionResult."""
    if success:
        return ExtractionResult(
            success=True,
            profile_data=_make_profile_data(),
        )
    return ExtractionResult(
        success=False,
        profile_data=None,
        error_message="Extraction failed",
    )


def _make_github_result(success: bool = True) -> GitHubExtractionResult:
    """Create a mock GitHubExtractionResult."""
    if success:
        return GitHubExtractionResult(
            success=True,
            data=GitHubData(),
        )
    return GitHubExtractionResult(
        success=False,
        data=None,
        error_message="GitHub unavailable",
    )


def _make_optimization_report() -> OptimizationReport:
    """Create a minimal OptimizationReport."""
    return OptimizationReport(
        sections=[
            SectionScore(
                section_name="headline",
                overall_score=60,
                factor_scores=[],
            )
        ],
        insights=[],
        overall_score=60,
    )


def _make_content_package() -> ContentPackage:
    """Create a minimal ContentPackage."""
    return ContentPackage(
        headline=HeadlineSuggestion(
            text="Optimized Headline",
            keywords_used=["Python", "Engineer"],
            value_proposition="Building great software",
        ),
        generated_at=datetime.now().isoformat(),
    )


# =============================================================================
# Custom Strategies
# =============================================================================

# Stages that halt the pipeline on failure (excluding GitHub which degrades gracefully)
HALTING_STAGES = st.sampled_from([1, 3, 4, 5])

# All stages including GitHub
ALL_STAGES = st.sampled_from([1, 2, 3, 4, 5])


# =============================================================================
# Property 17: Pipeline stage ordering and error propagation
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty17PipelineStageOrdering:
    """Property 17: Pipeline stage ordering and error propagation.

    **Validates: Requirements 6.3, 6.4, 6.5**

    For any pipeline execution, stages must execute in strict order
    (Scraper → GitHub → Analyzer → ContentCreator → Approval), and if any
    stage fails (except GitHub which degrades gracefully), no subsequent
    stages should execute. The run metadata should record the failure.
    """

    @given(failing_stage=HALTING_STAGES)
    @settings(max_examples=30, deadline=None)
    async def test_failure_at_stage_halts_subsequent_stages(
        self, failing_stage: int
    ):
        """When a non-GitHub stage fails, subsequent stages are NOT called."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        # Set up orchestrator internal state
        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Track which stages were called
        stages_called: list[int] = []

        # Stage 1: Profile Scraper
        mock_scraper = AsyncMock()
        if failing_stage == 1:
            mock_scraper.extract = AsyncMock(
                return_value=_make_extraction_result(success=False)
            )
        else:
            mock_scraper.extract = AsyncMock(
                return_value=_make_extraction_result(success=True)
            )
        orchestrator._profile_scraper = mock_scraper

        # Stage 2: GitHub Extractor (always mocked as successful for this test)
        mock_github = MagicMock()
        mock_github.extract = AsyncMock(
            return_value=_make_github_result(success=True)
        )

        # Stage 3: Analyzer Agent
        mock_analyzer = AsyncMock()
        if failing_stage == 3:
            mock_analyzer.analyze = AsyncMock(
                side_effect=RuntimeError("Analyzer failed")
            )
        else:
            mock_analyzer.analyze = AsyncMock(
                return_value=_make_optimization_report()
            )
        orchestrator._analyzer_agent = mock_analyzer

        # Stage 4: Content Creator Agent
        mock_content_creator = AsyncMock()
        if failing_stage == 4:
            mock_content_creator.generate = AsyncMock(
                side_effect=RuntimeError("Content creator failed")
            )
        else:
            mock_content_creator.generate = AsyncMock(
                return_value=_make_content_package()
            )
        orchestrator._content_creator_agent = mock_content_creator

        # Stage 5: Approval Workflow
        mock_approval = AsyncMock()
        if failing_stage == 5:
            mock_approval.submit_for_review = AsyncMock(
                side_effect=RuntimeError("Approval workflow failed")
            )
        else:
            mock_approval.submit_for_review = AsyncMock(return_value=None)
        orchestrator._approval_workflow = mock_approval

        # Mock data store to not write files
        mock_data_store = MagicMock()
        mock_data_store.save_profile_snapshot = MagicMock(return_value="path")
        mock_data_store.save_optimization_report = MagicMock(return_value="path")
        mock_data_store.save_content_package = MagicMock(return_value="path")
        mock_data_store.save_run_metadata = MagicMock(return_value="path")
        orchestrator._data_store = mock_data_store

        # Execute the pipeline
        result = await orchestrator.execute()

        # Verify the pipeline status is FAILED
        assert result.status == PipelineStatus.FAILED, (
            f"Pipeline should be FAILED when stage {failing_stage} fails, "
            f"got {result.status}"
        )

        # Verify error is recorded in metadata (Req 6.5)
        assert result.error is not None, (
            "Run metadata should contain an error message when pipeline fails"
        )

        # Verify stages AFTER the failing stage were NOT called
        if failing_stage == 1:
            # Scraper failed → Analyzer, Content Creator, Approval not called
            mock_analyzer.analyze.assert_not_called()
            mock_content_creator.generate.assert_not_called()
            mock_approval.submit_for_review.assert_not_called()
        elif failing_stage == 3:
            # Analyzer failed → Content Creator, Approval not called
            mock_scraper.extract.assert_called_once()
            mock_content_creator.generate.assert_not_called()
            mock_approval.submit_for_review.assert_not_called()
        elif failing_stage == 4:
            # Content Creator failed → Approval not called
            mock_scraper.extract.assert_called_once()
            mock_analyzer.analyze.assert_called_once()
            mock_approval.submit_for_review.assert_not_called()
        elif failing_stage == 5:
            # Approval failed → all prior stages were called
            mock_scraper.extract.assert_called_once()
            mock_analyzer.analyze.assert_called_once()
            mock_content_creator.generate.assert_called_once()

    @given(data=st.data())
    @settings(max_examples=20, deadline=None)
    async def test_successful_pipeline_calls_all_stages_in_order(self, data):
        """When all stages succeed, they are all called in correct order."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Track call order
        call_order: list[str] = []

        async def mock_extract(url):
            call_order.append("scraper")
            return _make_extraction_result(success=True)

        async def mock_github_extract():
            call_order.append("github")
            return _make_github_result(success=True)

        async def mock_analyze(profile, github_data):
            call_order.append("analyzer")
            return _make_optimization_report()

        async def mock_generate(report, profile, github_data):
            call_order.append("content_creator")
            return _make_content_package()

        async def mock_submit(content, profile):
            call_order.append("approval")
            return None

        mock_scraper = AsyncMock()
        mock_scraper.extract = mock_extract
        orchestrator._profile_scraper = mock_scraper

        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = mock_analyze
        orchestrator._analyzer_agent = mock_analyzer

        mock_content_creator = AsyncMock()
        mock_content_creator.generate = mock_generate
        orchestrator._content_creator_agent = mock_content_creator

        mock_approval = AsyncMock()
        mock_approval.submit_for_review = mock_submit
        orchestrator._approval_workflow = mock_approval

        mock_data_store = MagicMock()
        mock_data_store.save_profile_snapshot = MagicMock(return_value="path")
        mock_data_store.save_optimization_report = MagicMock(return_value="path")
        mock_data_store.save_content_package = MagicMock(return_value="path")
        mock_data_store.save_run_metadata = MagicMock(return_value="path")
        orchestrator._data_store = mock_data_store

        result = await orchestrator.execute()

        # Verify all stages were called
        assert result.status == PipelineStatus.COMPLETED
        assert "scraper" in call_order
        assert "analyzer" in call_order
        assert "content_creator" in call_order
        assert "approval" in call_order

        # Verify strict ordering (Req 6.3)
        assert call_order.index("scraper") < call_order.index("analyzer"), (
            "Scraper must execute before Analyzer"
        )
        assert call_order.index("analyzer") < call_order.index("content_creator"), (
            "Analyzer must execute before Content Creator"
        )
        assert call_order.index("content_creator") < call_order.index("approval"), (
            "Content Creator must execute before Approval"
        )

    @settings(max_examples=20, deadline=None)
    @given(data=st.data())
    async def test_github_failure_does_not_halt_pipeline(self, data):
        """GitHub extraction failure does NOT halt the pipeline (graceful degradation)."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Scraper succeeds
        mock_scraper = AsyncMock()
        mock_scraper.extract = AsyncMock(
            return_value=_make_extraction_result(success=True)
        )
        orchestrator._profile_scraper = mock_scraper

        # Analyzer succeeds (called with github_data=None due to failure)
        mock_analyzer = AsyncMock()
        mock_analyzer.analyze = AsyncMock(return_value=_make_optimization_report())
        orchestrator._analyzer_agent = mock_analyzer

        # Content creator succeeds
        mock_content_creator = AsyncMock()
        mock_content_creator.generate = AsyncMock(
            return_value=_make_content_package()
        )
        orchestrator._content_creator_agent = mock_content_creator

        # Approval succeeds
        mock_approval = AsyncMock()
        mock_approval.submit_for_review = AsyncMock(return_value=None)
        orchestrator._approval_workflow = mock_approval

        mock_data_store = MagicMock()
        mock_data_store.save_profile_snapshot = MagicMock(return_value="path")
        mock_data_store.save_optimization_report = MagicMock(return_value="path")
        mock_data_store.save_content_package = MagicMock(return_value="path")
        mock_data_store.save_run_metadata = MagicMock(return_value="path")
        orchestrator._data_store = mock_data_store

        # Patch GitHubExtractor to fail
        with patch(
            "linkedin_optimizer.orchestrator.GitHubExtractor"
        ) as MockGHExtractor:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract = AsyncMock(
                side_effect=RuntimeError("GitHub API timeout")
            )
            MockGHExtractor.return_value = mock_gh_instance

            result = await orchestrator.execute()

        # Pipeline should COMPLETE despite GitHub failure (Req 7.4)
        assert result.status == PipelineStatus.COMPLETED, (
            f"Pipeline should complete with GitHub failure (graceful degradation), "
            f"got {result.status}"
        )

        # Subsequent stages should still be called
        mock_analyzer.analyze.assert_called_once()
        mock_content_creator.generate.assert_called_once()
        mock_approval.submit_for_review.assert_called_once()

    @given(failing_stage=HALTING_STAGES)
    @settings(max_examples=20, deadline=None)
    async def test_run_metadata_logged_on_failure(self, failing_stage: int):
        """Run metadata is always logged even on pipeline failure (Req 6.5)."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Set up stages with the specified one failing
        mock_scraper = AsyncMock()
        if failing_stage == 1:
            mock_scraper.extract = AsyncMock(
                return_value=_make_extraction_result(success=False)
            )
        else:
            mock_scraper.extract = AsyncMock(
                return_value=_make_extraction_result(success=True)
            )
        orchestrator._profile_scraper = mock_scraper

        mock_analyzer = AsyncMock()
        if failing_stage == 3:
            mock_analyzer.analyze = AsyncMock(
                side_effect=RuntimeError("Analyzer failed")
            )
        else:
            mock_analyzer.analyze = AsyncMock(
                return_value=_make_optimization_report()
            )
        orchestrator._analyzer_agent = mock_analyzer

        mock_content_creator = AsyncMock()
        if failing_stage == 4:
            mock_content_creator.generate = AsyncMock(
                side_effect=RuntimeError("Content creator failed")
            )
        else:
            mock_content_creator.generate = AsyncMock(
                return_value=_make_content_package()
            )
        orchestrator._content_creator_agent = mock_content_creator

        mock_approval = AsyncMock()
        if failing_stage == 5:
            mock_approval.submit_for_review = AsyncMock(
                side_effect=RuntimeError("Approval failed")
            )
        else:
            mock_approval.submit_for_review = AsyncMock(return_value=None)
        orchestrator._approval_workflow = mock_approval

        mock_data_store = MagicMock()
        mock_data_store.save_profile_snapshot = MagicMock(return_value="path")
        mock_data_store.save_optimization_report = MagicMock(return_value="path")
        mock_data_store.save_content_package = MagicMock(return_value="path")
        mock_data_store.save_run_metadata = MagicMock(return_value="path")
        orchestrator._data_store = mock_data_store

        # Patch GitHubExtractor for stage 2
        with patch(
            "linkedin_optimizer.orchestrator.GitHubExtractor"
        ) as MockGHExtractor:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract = AsyncMock(
                return_value=_make_github_result(success=True)
            )
            MockGHExtractor.return_value = mock_gh_instance

            result = await orchestrator.execute()

        # Metadata should always be logged (Req 6.5)
        mock_data_store.save_run_metadata.assert_called_once()

        # Verify the saved metadata matches the returned result
        saved_metadata = mock_data_store.save_run_metadata.call_args[0][0]
        assert saved_metadata.status == PipelineStatus.FAILED
        assert saved_metadata.error is not None
        assert saved_metadata.run_id == result.run_id


# =============================================================================
# Property 18: Run queue serialization
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty18RunQueueSerialization:
    """Property 18: Run queue serialization.

    **Validates: Requirements 6.7**

    For any two concurrent pipeline triggers, only one should execute at
    a time. The second trigger should be queued and execute only after the
    first run completes.
    """

    @given(num_concurrent=st.integers(min_value=2, max_value=5))
    @settings(max_examples=20, deadline=None)
    async def test_enqueue_run_increments_queue_position(self, num_concurrent: int):
        """enqueue_run() returns incrementing positions for queued runs."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.RUNNING
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = "run_active"

        # Enqueue multiple runs and verify positions increment
        positions = []
        for _ in range(num_concurrent):
            pos = orchestrator.enqueue_run()
            positions.append(pos)

        # Positions should be 1, 2, 3, ... num_concurrent
        assert positions == list(range(1, num_concurrent + 1)), (
            f"Expected positions {list(range(1, num_concurrent + 1))}, "
            f"got {positions}"
        )

        # Queue size should match
        assert orchestrator._run_queue.qsize() == num_concurrent

    @given(data=st.data())
    @settings(max_examples=10, deadline=None)
    async def test_trigger_on_demand_acquires_lock(self, data):
        """trigger_on_demand() acquires the lock before executing the pipeline."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Track lock state during execution
        lock_was_held_during_execute = False

        async def mock_execute_that_checks_lock():
            nonlocal lock_was_held_during_execute
            lock_was_held_during_execute = orchestrator._lock.locked()
            return RunMetadata(
                run_id="run_test",
                start_time=datetime.now(),
                end_time=datetime.now(),
                status=PipelineStatus.COMPLETED,
                summary="Test run",
                error=None,
            )

        orchestrator.execute = mock_execute_that_checks_lock

        result = await orchestrator.trigger_on_demand()

        assert lock_was_held_during_execute, (
            "Lock should be held during pipeline execution"
        )
        assert result.status == PipelineStatus.COMPLETED

    @given(data=st.data())
    @settings(max_examples=10, deadline=None)
    async def test_concurrent_triggers_serialize_execution(self, data):
        """Multiple concurrent trigger_on_demand() calls serialize execution."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        # Track execution timing — verify no overlap
        execution_log: list[tuple[str, float]] = []
        max_concurrent = 0
        current_concurrent = 0
        concurrent_lock = asyncio.Lock()

        async def mock_execute():
            nonlocal max_concurrent, current_concurrent
            async with concurrent_lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent

            execution_log.append(("start", asyncio.get_event_loop().time()))
            # Simulate work
            await asyncio.sleep(0.01)
            execution_log.append(("end", asyncio.get_event_loop().time()))

            async with concurrent_lock:
                current_concurrent -= 1

            return RunMetadata(
                run_id=f"run_{uuid.uuid4().hex[:8]}",
                start_time=datetime.now(),
                end_time=datetime.now(),
                status=PipelineStatus.COMPLETED,
                summary="Completed",
                error=None,
            )

        orchestrator.execute = mock_execute

        # Trigger multiple concurrent runs
        tasks = [
            asyncio.create_task(orchestrator.trigger_on_demand())
            for _ in range(3)
        ]
        results = await asyncio.gather(*tasks)

        # All should complete successfully
        assert all(r.status == PipelineStatus.COMPLETED for r in results)

        # Maximum concurrent should be 1 (serialized via lock)
        assert max_concurrent == 1, (
            f"Expected max 1 concurrent execution, got {max_concurrent}. "
            "The lock should prevent concurrent pipeline executions."
        )

    @given(num_triggers=st.integers(min_value=2, max_value=4))
    @settings(max_examples=10, deadline=None)
    async def test_all_queued_triggers_eventually_execute(self, num_triggers: int):
        """All queued triggers eventually execute after the lock is released."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        execution_count = 0
        count_lock = asyncio.Lock()

        async def mock_execute():
            nonlocal execution_count
            async with count_lock:
                execution_count += 1
            await asyncio.sleep(0.005)
            return RunMetadata(
                run_id=f"run_{uuid.uuid4().hex[:8]}",
                start_time=datetime.now(),
                end_time=datetime.now(),
                status=PipelineStatus.COMPLETED,
                summary="Completed",
                error=None,
            )

        orchestrator.execute = mock_execute

        # Fire off all triggers concurrently
        tasks = [
            asyncio.create_task(orchestrator.trigger_on_demand())
            for _ in range(num_triggers)
        ]
        results = await asyncio.gather(*tasks)

        # All triggers should have completed
        assert len(results) == num_triggers, (
            f"Expected {num_triggers} results, got {len(results)}"
        )
        assert all(r.status == PipelineStatus.COMPLETED for r in results)

        # Each trigger should have resulted in an execution
        assert execution_count == num_triggers, (
            f"Expected {num_triggers} executions, got {execution_count}"
        )

    @given(data=st.data())
    @settings(max_examples=10, deadline=None)
    async def test_lock_released_after_failure(self, data):
        """The lock is released even when pipeline execution fails."""
        config = _make_config()

        with patch.object(PipelineOrchestrator, "__init__", lambda self, cfg: None):
            orchestrator = PipelineOrchestrator.__new__(PipelineOrchestrator)

        orchestrator._config = config
        orchestrator._status = PipelineStatus.IDLE
        orchestrator._lock = asyncio.Lock()
        orchestrator._run_queue = asyncio.Queue()
        orchestrator._current_run_id = None

        call_count = 0

        async def mock_execute():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call fails
                return RunMetadata(
                    run_id="run_failed",
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    status=PipelineStatus.FAILED,
                    summary=None,
                    error="Test failure",
                )
            else:
                # Subsequent calls succeed
                return RunMetadata(
                    run_id="run_success",
                    start_time=datetime.now(),
                    end_time=datetime.now(),
                    status=PipelineStatus.COMPLETED,
                    summary="Completed",
                    error=None,
                )

        orchestrator.execute = mock_execute

        # First trigger fails
        result1 = await orchestrator.trigger_on_demand()
        assert result1.status == PipelineStatus.FAILED

        # Lock should be released — second trigger should work
        assert not orchestrator._lock.locked(), (
            "Lock should be released after failed execution"
        )

        # Second trigger succeeds
        result2 = await orchestrator.trigger_on_demand()
        assert result2.status == PipelineStatus.COMPLETED
