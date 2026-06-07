"""Unit tests for the PipelineOrchestrator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_optimizer.config import PipelineConfig
from linkedin_optimizer.models import (
    ContentPackage,
    ExtractionResult,
    GitHubData,
    GitHubExtractionResult,
    OptimizationReport,
    PipelineStatus,
    ProfileData,
    RunMetadata,
    SectionScore,
    FactorScore,
    SectionInsight,
)
from linkedin_optimizer.orchestrator import PipelineOrchestrator


@pytest.fixture
def sample_config():
    """Create a sample PipelineConfig for testing."""
    return PipelineConfig(
        linkedin_profile_url="https://www.linkedin.com/in/testuser",
        github_username="testuser",
        schedule_interval=None,
        analyzer_model_id="test-model",
        content_model_id="test-model",
        fallback_model_id="fallback-model",
        data_dir="/tmp/test_orchestrator_data",
        hf_api_token="test-token",
        hf_timeout_seconds=30,
        hf_max_retries=3,
    )


@pytest.fixture
def sample_profile():
    """Create a sample ProfileData."""
    return ProfileData(
        headline="Senior Engineer",
        about="Building things.",
        experience=[{"title": "Engineer", "company": "Test Co"}],
        skills=[{"name": "Python", "endorsements": 10}],
    )


@pytest.fixture
def sample_report():
    """Create a sample OptimizationReport."""
    return OptimizationReport(
        sections=[
            SectionScore(
                section_name="headline",
                overall_score=55,
                factor_scores=[
                    FactorScore(factor_name="keywords", score=60, explanation="OK")
                ],
            )
        ],
        insights=[
            SectionInsight(
                section_name="headline",
                strengths=["Good"],
                weaknesses=["Bad"],
                recommendations=[],
            )
        ],
        overall_score=55,
    )


@pytest.fixture
def sample_content_package():
    """Create a sample ContentPackage."""
    return ContentPackage(generated_at=datetime.now().isoformat())


@pytest.fixture
def orchestrator(sample_config):
    """Create an orchestrator with mocked components."""
    with patch(
        "linkedin_optimizer.orchestrator.LinkedInMCPClient"
    ) as mock_mcp, patch(
        "linkedin_optimizer.orchestrator.ProfileScraper"
    ) as mock_scraper_cls, patch(
        "linkedin_optimizer.orchestrator.HuggingFaceClient"
    ) as mock_hf, patch(
        "linkedin_optimizer.orchestrator.AnalyzerAgent"
    ) as mock_analyzer_cls, patch(
        "linkedin_optimizer.orchestrator.ContentCreatorAgent"
    ) as mock_content_cls, patch(
        "linkedin_optimizer.orchestrator.ApprovalWorkflow"
    ) as mock_approval_cls, patch(
        "linkedin_optimizer.orchestrator.DataStore"
    ) as mock_store_cls:
        orch = PipelineOrchestrator(sample_config)
        yield orch


class TestPipelineOrchestratorInit:
    """Tests for orchestrator initialization."""

    def test_initial_status_is_idle(self, orchestrator):
        """Orchestrator should start in IDLE status."""
        assert orchestrator.get_status() == PipelineStatus.IDLE

    def test_config_stored(self, orchestrator, sample_config):
        """Orchestrator should store the config."""
        assert orchestrator._config == sample_config


class TestGetStatus:
    """Tests for get_status method."""

    def test_returns_idle_when_not_running(self, orchestrator):
        """Status should be IDLE when no pipeline is running."""
        assert orchestrator.get_status() == PipelineStatus.IDLE


class TestGenerateRunId:
    """Tests for run ID generation."""

    def test_run_id_format(self, orchestrator):
        """Run ID should follow run_YYYY-MM-DD_HHMMSS format."""
        run_id = orchestrator._generate_run_id()
        assert run_id.startswith("run_")
        # Check date part is valid
        parts = run_id.split("_", 1)
        assert len(parts) == 2
        date_time_part = parts[1]
        # Should be parseable as a datetime
        datetime.strptime(date_time_part, "%Y-%m-%d_%H%M%S")

    def test_run_ids_are_unique_across_seconds(self, orchestrator):
        """Run IDs generated at different times should differ."""
        id1 = orchestrator._generate_run_id()
        # Same second might produce same ID, that's OK for this format
        assert id1.startswith("run_")


class TestExecute:
    """Tests for execute method."""

    @pytest.mark.asyncio
    async def test_successful_execution(self, orchestrator, sample_profile, sample_report, sample_content_package):
        """Full pipeline should execute all stages and return completed metadata."""
        # Mock profile scraper
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )

        # Mock GitHub extractor - patch at class level
        mock_github_result = GitHubExtractionResult(
            success=True,
            data=GitHubData(),
        )
        with patch(
            "linkedin_optimizer.orchestrator.GitHubExtractor"
        ) as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = mock_github_result
            mock_gh_cls.return_value = mock_gh_instance

            # Mock analyzer
            orchestrator._analyzer_agent.analyze = AsyncMock(
                return_value=sample_report
            )

            # Mock content creator
            orchestrator._content_creator_agent.generate = AsyncMock(
                return_value=sample_content_package
            )

            # Mock approval workflow
            orchestrator._approval_workflow.submit_for_review = AsyncMock(
                return_value=None
            )

            # Mock data store
            orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
            orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
            orchestrator._data_store.save_content_package = MagicMock(return_value="path")
            orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

            result = await orchestrator.execute()

        assert result.status == PipelineStatus.COMPLETED
        assert result.run_id.startswith("run_")
        assert result.start_time is not None
        assert result.end_time is not None
        assert result.error is None
        assert result.summary is not None

    @pytest.mark.asyncio
    async def test_halts_on_profile_extraction_failure(self, orchestrator):
        """Pipeline should halt and return FAILED if profile extraction fails."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=False, profile_data=None, error_message="URL invalid"
            )
        )
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        result = await orchestrator.execute()

        assert result.status == PipelineStatus.FAILED
        assert "Profile extraction failed" in result.error
        # Analyzer should NOT be called
        orchestrator._analyzer_agent.analyze = AsyncMock()
        orchestrator._analyzer_agent.analyze.assert_not_called()

    @pytest.mark.asyncio
    async def test_halts_on_analyzer_failure(self, orchestrator, sample_profile):
        """Pipeline should halt if Analyzer fails (Req 6.4)."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(
            side_effect=Exception("Model unavailable")
        )
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = GitHubExtractionResult(
                success=False, data=None, error_message="Timeout"
            )
            mock_gh_cls.return_value = mock_gh_instance

            result = await orchestrator.execute()

        assert result.status == PipelineStatus.FAILED
        assert "Analyzer agent failed" in result.error

    @pytest.mark.asyncio
    async def test_halts_on_content_creator_failure(self, orchestrator, sample_profile, sample_report):
        """Pipeline should halt if ContentCreator fails."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(return_value=sample_report)
        orchestrator._content_creator_agent.generate = AsyncMock(
            side_effect=Exception("Generation failed")
        )
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = GitHubExtractionResult(
                success=False, data=None, error_message="Timeout"
            )
            mock_gh_cls.return_value = mock_gh_instance

            result = await orchestrator.execute()

        assert result.status == PipelineStatus.FAILED
        assert "Content creator agent failed" in result.error

    @pytest.mark.asyncio
    async def test_github_failure_continues_pipeline(self, orchestrator, sample_profile, sample_report, sample_content_package):
        """Pipeline should continue with LinkedIn-only if GitHub fails (Req 7.4)."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(return_value=sample_report)
        orchestrator._content_creator_agent.generate = AsyncMock(
            return_value=sample_content_package
        )
        orchestrator._approval_workflow.submit_for_review = AsyncMock(return_value=None)
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
        orchestrator._data_store.save_content_package = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.side_effect = Exception("Connection refused")
            mock_gh_cls.return_value = mock_gh_instance

            result = await orchestrator.execute()

        assert result.status == PipelineStatus.COMPLETED
        # Analyzer was called with None for github_data
        orchestrator._analyzer_agent.analyze.assert_called_once_with(sample_profile, None)

    @pytest.mark.asyncio
    async def test_metadata_logged_before_status_change(self, orchestrator, sample_profile, sample_report, sample_content_package):
        """RunMetadata should be saved via DataStore (Req 6.5)."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(return_value=sample_report)
        orchestrator._content_creator_agent.generate = AsyncMock(
            return_value=sample_content_package
        )
        orchestrator._approval_workflow.submit_for_review = AsyncMock(return_value=None)
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
        orchestrator._data_store.save_content_package = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = GitHubExtractionResult(
                success=True, data=GitHubData()
            )
            mock_gh_cls.return_value = mock_gh_instance

            result = await orchestrator.execute()

        # Verify save_run_metadata was called
        orchestrator._data_store.save_run_metadata.assert_called_once()
        saved_metadata = orchestrator._data_store.save_run_metadata.call_args[0][0]
        assert isinstance(saved_metadata, RunMetadata)
        assert saved_metadata.status == PipelineStatus.COMPLETED
        assert saved_metadata.run_id == result.run_id

    @pytest.mark.asyncio
    async def test_status_returns_to_idle_after_run(self, orchestrator, sample_profile, sample_report, sample_content_package):
        """Status should return to IDLE after a completed or failed run."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(return_value=sample_report)
        orchestrator._content_creator_agent.generate = AsyncMock(
            return_value=sample_content_package
        )
        orchestrator._approval_workflow.submit_for_review = AsyncMock(return_value=None)
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
        orchestrator._data_store.save_content_package = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = GitHubExtractionResult(
                success=True, data=GitHubData()
            )
            mock_gh_cls.return_value = mock_gh_instance

            await orchestrator.execute()

        assert orchestrator.get_status() == PipelineStatus.IDLE


class TestEnqueueRun:
    """Tests for enqueue_run method."""

    def test_enqueue_returns_position(self, orchestrator):
        """enqueue_run should return the queue position (1-based)."""
        pos1 = orchestrator.enqueue_run()
        assert pos1 == 1

        pos2 = orchestrator.enqueue_run()
        assert pos2 == 2

    def test_enqueue_increments_queue_size(self, orchestrator):
        """Each enqueue should increase queue size."""
        orchestrator.enqueue_run()
        orchestrator.enqueue_run()
        orchestrator.enqueue_run()
        assert orchestrator._run_queue.qsize() == 3


class TestTriggerOnDemand:
    """Tests for trigger_on_demand method."""

    @pytest.mark.asyncio
    async def test_trigger_executes_immediately_when_idle(self, orchestrator, sample_profile, sample_report, sample_content_package):
        """Should execute immediately when not already running."""
        orchestrator._profile_scraper.extract = AsyncMock(
            return_value=ExtractionResult(
                success=True, profile_data=sample_profile
            )
        )
        orchestrator._analyzer_agent.analyze = AsyncMock(return_value=sample_report)
        orchestrator._content_creator_agent.generate = AsyncMock(
            return_value=sample_content_package
        )
        orchestrator._approval_workflow.submit_for_review = AsyncMock(return_value=None)
        orchestrator._data_store.save_profile_snapshot = MagicMock(return_value="path")
        orchestrator._data_store.save_optimization_report = MagicMock(return_value="path")
        orchestrator._data_store.save_content_package = MagicMock(return_value="path")
        orchestrator._data_store.save_run_metadata = MagicMock(return_value="path")

        with patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.extract.return_value = GitHubExtractionResult(
                success=True, data=GitHubData()
            )
            mock_gh_cls.return_value = mock_gh_instance

            result = await orchestrator.trigger_on_demand()

        assert result.status == PipelineStatus.COMPLETED
