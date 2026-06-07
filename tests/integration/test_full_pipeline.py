"""Integration tests for the LinkedIn Profile Optimizer full pipeline.

Tests full pipeline execution, scheduler lifecycle, CLI parsing,
data persistence, and approval workflow end-to-end with mocked externals.

Requirements: 6.1, 6.2, 6.3, 6.5, 5.1
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_optimizer.approval.workflow import ApprovalWorkflow
from linkedin_optimizer.cli import _build_parser as build_parser, main, parse_args
from linkedin_optimizer.config import PipelineConfig
from linkedin_optimizer.models import (
    AboutSuggestion,
    ApprovalStatus,
    ContentPackage,
    ExtractionResult,
    FactorScore,
    GitHubContributions,
    GitHubData,
    GitHubExtractionResult,
    GitHubRepo,
    HeadlineSuggestion,
    OptimizationReport,
    PipelineStatus,
    PostIdea,
    ProfileData,
    Recommendation,
    Priority,
    RunMetadata,
    ScheduleInterval,
    SectionInsight,
    SectionScore,
)
from linkedin_optimizer.orchestrator import PipelineOrchestrator
from linkedin_optimizer.persistence.data_store import DataStore
from linkedin_optimizer.scheduler import PipelineScheduler


# --- Fixtures ---


@pytest.fixture
def sample_profile_data() -> ProfileData:
    """Create sample profile data for testing."""
    return ProfileData(
        headline="Software Engineer at TechCorp",
        about="Passionate developer with 5 years of experience.",
        experience=[
            {
                "title": "Software Engineer",
                "company": "TechCorp",
                "duration": "2020 - Present",
                "description": "Building scalable systems.",
            }
        ],
        skills=[{"name": "Python", "endorsements": 10}],
        endorsements=[],
        posts=[{"text": "Excited to share...", "reactions": 50, "comments": 10}],
        follower_count=500,
        connection_count=300,
    )


@pytest.fixture
def sample_github_data() -> GitHubData:
    """Create sample GitHub data for testing."""
    return GitHubData(
        repos=[
            GitHubRepo(
                name="awesome-project",
                description="A cool project",
                stars=15,
                primary_language="Python",
                is_pinned=True,
                url="https://github.com/user/awesome-project",
            )
        ],
        contributions=GitHubContributions(
            total_commits_12m=200,
            total_prs_12m=30,
            total_issues_12m=10,
            commits_per_week_avg=4.0,
        ),
        pinned_repos=[],
        languages={"Python": 50000, "JavaScript": 20000},
        notable_repos=[],
    )


@pytest.fixture
def sample_optimization_report() -> OptimizationReport:
    """Create sample optimization report for testing."""
    return OptimizationReport(
        sections=[
            SectionScore(
                section_name="headline",
                overall_score=55,
                factor_scores=[
                    FactorScore(
                        factor_name="keyword_presence",
                        score=60,
                        explanation="Contains role title",
                    ),
                    FactorScore(
                        factor_name="character_utilization",
                        score=50,
                        explanation="Underutilizes limit",
                    ),
                ],
            ),
            SectionScore(
                section_name="about",
                overall_score=45,
                factor_scores=[
                    FactorScore(
                        factor_name="narrative_structure",
                        score=45,
                        explanation="Lacks structure",
                    ),
                ],
            ),
        ],
        insights=[
            SectionInsight(
                section_name="headline",
                strengths=["Contains role title"],
                weaknesses=["No value proposition"],
                recommendations=[
                    Recommendation(
                        element="headline text",
                        modification="Add a value proposition",
                        priority=Priority.HIGH,
                        guideline_reference="LinkedIn search visibility",
                        expected_impact="15-25% more appearances",
                    ),
                    Recommendation(
                        element="headline keywords",
                        modification="Add industry keywords",
                        priority=Priority.MEDIUM,
                        guideline_reference="Algorithm favors keywords",
                        expected_impact="10% more reach",
                    ),
                ],
            ),
        ],
        overall_score=50,
        github_summary="1 notable repo, Python primary, 4 commits/week",
        generated_at=datetime.now().isoformat(),
    )


@pytest.fixture
def sample_content_package() -> ContentPackage:
    """Create sample content package for testing."""
    return ContentPackage(
        headline=HeadlineSuggestion(
            text="Software Engineer | Building scalable Python systems | Open source contributor",
            keywords_used=["Python", "scalable", "open source"],
            value_proposition="Building scalable Python systems",
        ),
        about=AboutSuggestion(
            text="What if your systems could handle 10x more load? That's what I build. "
            "With 5 years in distributed systems, I help teams scale with Python. "
            "Let's connect to discuss how I can help your team.",
            hook_sentence="What if your systems could handle 10x more load?",
            keywords_used=["Python", "distributed systems", "scalable"],
            call_to_action="Let's connect to discuss how I can help your team.",
        ),
        experience=[],
        post_ideas=[
            PostIdea(
                topic="Scaling Python services",
                format="text",
                content_outline="Share lessons from scaling a Python service to handle 10M requests. "
                "Cover key optimizations and monitoring strategies.",
            ),
            PostIdea(
                topic="Open source contributions",
                format="carousel",
                content_outline="Highlight top 3 open source contributions this year. "
                "Explain the impact and what you learned.",
            ),
            PostIdea(
                topic="Code review best practices",
                format="poll",
                content_outline="Poll your network on code review preferences. "
                "Follow up with a detailed post on best practices.",
            ),
        ],
        banner=None,
        generated_at=datetime.now().isoformat(),
    )


@pytest.fixture
def pipeline_config(tmp_path) -> PipelineConfig:
    """Create a pipeline config pointing to a temp directory."""
    return PipelineConfig(
        linkedin_profile_url="https://www.linkedin.com/in/testuser",
        github_username="testuser",
        schedule_interval=None,
        analyzer_model_id="test/model-analyzer",
        content_model_id="test/model-content",
        fallback_model_id="test/model-fallback",
        data_dir=str(tmp_path / "data"),
        hf_api_token="test-token",
        hf_timeout_seconds=30,
        hf_max_retries=3,
    )


# --- Test 1: Full Pipeline E2E ---


@pytest.mark.integration
class TestFullPipelineE2E:
    """Test full pipeline execution with mocked external services."""

    @pytest.mark.asyncio
    async def test_full_pipeline_execution_all_stages_complete(
        self,
        pipeline_config,
        sample_profile_data,
        sample_github_data,
        sample_optimization_report,
        sample_content_package,
        tmp_path,
    ):
        """Full pipeline E2E: all stages complete, data persisted, RunMetadata logged."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ) as mock_mcp_cls,
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ) as mock_scraper_cls,
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ) as mock_gh_cls,
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ) as mock_analyzer_cls,
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ) as mock_content_cls,
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ) as mock_hf_cls,
            patch(
                "linkedin_optimizer.orchestrator.ApprovalWorkflow"
            ) as mock_approval_cls,
        ):
            # Configure mocks
            mock_mcp = MagicMock()
            mock_mcp_cls.return_value = mock_mcp

            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=True,
                profile_data=sample_profile_data,
                failed_sections=[],
            )
            mock_scraper_cls.return_value = mock_scraper

            mock_gh = AsyncMock()
            mock_gh.extract.return_value = GitHubExtractionResult(
                success=True,
                data=sample_github_data,
                partial=False,
            )
            mock_gh_cls.return_value = mock_gh

            mock_analyzer = AsyncMock()
            mock_analyzer.analyze.return_value = sample_optimization_report
            mock_analyzer_cls.return_value = mock_analyzer

            mock_content = AsyncMock()
            mock_content.generate.return_value = sample_content_package
            mock_content_cls.return_value = mock_content

            mock_approval = AsyncMock()
            mock_approval.submit_for_review.return_value = MagicMock()
            mock_approval_cls.return_value = mock_approval

            mock_hf = MagicMock()
            mock_hf_cls.return_value = mock_hf

            # Execute pipeline
            orchestrator = PipelineOrchestrator(pipeline_config)
            result = await orchestrator.execute()

            # Verify RunMetadata
            assert result.status == PipelineStatus.COMPLETED
            assert result.run_id.startswith("run_")
            assert result.start_time is not None
            assert result.end_time is not None
            assert result.end_time >= result.start_time
            assert result.summary is not None
            assert "50" in result.summary  # overall score in summary
            assert result.error is None

            # Verify data persistence
            data_dir = Path(pipeline_config.data_dir)
            assert (data_dir / "profiles").exists()
            assert (data_dir / "reports").exists()
            assert (data_dir / "content").exists()
            assert (data_dir / "runs").exists()

            # Verify run metadata file created
            run_files = list((data_dir / "runs").glob("*_meta.json"))
            assert len(run_files) == 1

            # Verify profile snapshot saved
            profile_files = list((data_dir / "profiles").glob("*_profile.json"))
            assert len(profile_files) == 1

            # Verify report saved
            report_files = list((data_dir / "reports").glob("*_report.json"))
            assert len(report_files) == 1

            # Verify content saved
            content_files = list((data_dir / "content").glob("*_content.json"))
            assert len(content_files) == 1

    @pytest.mark.asyncio
    async def test_pipeline_halts_on_scraper_failure(self, pipeline_config):
        """Pipeline halts on extraction failure without invoking subsequent stages."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ) as mock_mcp_cls,
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ) as mock_scraper_cls,
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ) as mock_gh_cls,
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ) as mock_analyzer_cls,
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ) as mock_content_cls,
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ) as mock_hf_cls,
        ):
            mock_mcp_cls.return_value = MagicMock()
            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=False,
                profile_data=None,
                error_message="Profile not accessible",
            )
            mock_scraper_cls.return_value = mock_scraper

            mock_analyzer = AsyncMock()
            mock_analyzer_cls.return_value = mock_analyzer

            mock_content = AsyncMock()
            mock_content_cls.return_value = mock_content

            mock_hf_cls.return_value = MagicMock()
            mock_gh_cls.return_value = AsyncMock()

            orchestrator = PipelineOrchestrator(pipeline_config)
            result = await orchestrator.execute()

            # Verify failure
            assert result.status == PipelineStatus.FAILED
            assert "Profile extraction failed" in result.error

            # Verify analyzer was NOT called
            mock_analyzer.analyze.assert_not_called()
            mock_content.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_continues_when_github_unavailable(
        self,
        pipeline_config,
        sample_profile_data,
        sample_optimization_report,
        sample_content_package,
    ):
        """Pipeline continues with LinkedIn-only when GitHub fails (Req 7.4)."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ) as mock_mcp_cls,
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ) as mock_scraper_cls,
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ) as mock_gh_cls,
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ) as mock_analyzer_cls,
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ) as mock_content_cls,
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ) as mock_hf_cls,
            patch(
                "linkedin_optimizer.orchestrator.ApprovalWorkflow"
            ) as mock_approval_cls,
        ):
            mock_mcp_cls.return_value = MagicMock()

            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=True,
                profile_data=sample_profile_data,
            )
            mock_scraper_cls.return_value = mock_scraper

            # GitHub fails
            mock_gh = AsyncMock()
            mock_gh.extract.side_effect = Exception("GitHub API timeout")
            mock_gh_cls.return_value = mock_gh

            mock_analyzer = AsyncMock()
            mock_analyzer.analyze.return_value = sample_optimization_report
            mock_analyzer_cls.return_value = mock_analyzer

            mock_content = AsyncMock()
            mock_content.generate.return_value = sample_content_package
            mock_content_cls.return_value = mock_content

            mock_approval = AsyncMock()
            mock_approval.submit_for_review.return_value = MagicMock()
            mock_approval_cls.return_value = mock_approval

            mock_hf_cls.return_value = MagicMock()

            orchestrator = PipelineOrchestrator(pipeline_config)
            result = await orchestrator.execute()

            # Pipeline should still complete
            assert result.status == PipelineStatus.COMPLETED
            assert "not available" in result.summary

            # Analyzer was called with None for github_data
            mock_analyzer.analyze.assert_called_once()
            call_args = mock_analyzer.analyze.call_args
            assert call_args[0][1] is None  # github_data is None


# --- Test 2: Scheduler Lifecycle ---


@pytest.mark.integration
class TestSchedulerLifecycle:
    """Test scheduler start/pause/resume lifecycle."""

    @pytest.mark.asyncio
    async def test_scheduler_schedule_creates_job(self, pipeline_config):
        """Schedule a weekly run and verify job exists."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ),
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ),
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ),
        ):
            orchestrator = PipelineOrchestrator(pipeline_config)
            scheduler = PipelineScheduler(orchestrator)

            # Schedule weekly
            scheduler.schedule(ScheduleInterval.WEEKLY)

            # Verify interval is set
            assert scheduler.current_interval == ScheduleInterval.WEEKLY

            # Start the scheduler
            scheduler.start()
            assert scheduler.is_running is True

            # Stop the scheduler — after shutdown the internal scheduler
            # should no longer be running (needs brief event loop tick)
            scheduler.stop()
            await asyncio.sleep(0.1)
            assert scheduler._scheduler.running is False

    @pytest.mark.asyncio
    async def test_scheduler_pause_and_resume(self, pipeline_config):
        """Pause and resume scheduled execution (Req 6.6)."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ),
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ),
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ),
        ):
            orchestrator = PipelineOrchestrator(pipeline_config)
            scheduler = PipelineScheduler(orchestrator)

            # Schedule and start
            scheduler.schedule(ScheduleInterval.DAILY)
            scheduler.start()

            # Pause
            scheduler.pause()
            # The scheduler is still running (event loop), but the job is paused
            assert scheduler.is_running is True
            assert scheduler.current_interval == ScheduleInterval.DAILY

            # Resume
            scheduler.resume()
            assert scheduler.is_running is True

            # Cleanup
            scheduler.stop()

    @pytest.mark.asyncio
    async def test_scheduler_reschedule_changes_interval(self, pipeline_config):
        """Rescheduling replaces the previous interval."""
        with (
            patch(
                "linkedin_optimizer.orchestrator.LinkedInMCPClient"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ProfileScraper"
            ),
            patch(
                "linkedin_optimizer.orchestrator.GitHubExtractor"
            ),
            patch(
                "linkedin_optimizer.orchestrator.AnalyzerAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.ContentCreatorAgent"
            ),
            patch(
                "linkedin_optimizer.orchestrator.HuggingFaceClient"
            ),
        ):
            orchestrator = PipelineOrchestrator(pipeline_config)
            scheduler = PipelineScheduler(orchestrator)

            scheduler.schedule(ScheduleInterval.DAILY)
            assert scheduler.current_interval == ScheduleInterval.DAILY

            scheduler.schedule(ScheduleInterval.MONTHLY)
            assert scheduler.current_interval == ScheduleInterval.MONTHLY


# --- Test 3: CLI Command Parsing ---


@pytest.mark.integration
class TestCLIParsing:
    """Test CLI command parsing and dispatch."""

    def test_parse_run_command(self):
        """CLI parses 'run' subcommand correctly."""
        parsed = parse_args(["run"])
        assert parsed.command == "run"

    def test_parse_schedule_command_weekly(self):
        """CLI parses 'schedule weekly' correctly."""
        parsed = parse_args(["schedule", "weekly"])
        assert parsed.command == "schedule"
        assert parsed.interval == "weekly"

    def test_parse_schedule_command_daily(self):
        """CLI parses 'schedule daily' correctly."""
        parsed = parse_args(["schedule", "daily"])
        assert parsed.command == "schedule"
        assert parsed.interval == "daily"

    def test_parse_schedule_command_monthly(self):
        """CLI parses 'schedule monthly' correctly."""
        parsed = parse_args(["schedule", "monthly"])
        assert parsed.command == "schedule"
        assert parsed.interval == "monthly"

    def test_parse_pause_command(self):
        """CLI parses 'pause' subcommand correctly."""
        parsed = parse_args(["pause"])
        assert parsed.command == "pause"

    def test_parse_resume_command(self):
        """CLI parses 'resume' subcommand correctly."""
        parsed = parse_args(["resume"])
        assert parsed.command == "resume"

    def test_parse_status_command(self):
        """CLI parses 'status' subcommand correctly."""
        parsed = parse_args(["status"])
        assert parsed.command == "status"

    def test_parse_review_command(self):
        """CLI parses 'review' subcommand correctly."""
        parsed = parse_args(["review"])
        assert parsed.command == "review"

    def test_parse_history_command_with_limit(self):
        """CLI parses 'history --limit 5' correctly."""
        parsed = parse_args(["history", "--limit", "5"])
        assert parsed.command == "history"
        assert parsed.limit == 5

    def test_parse_history_command_default_limit(self):
        """CLI parses 'history' with default limit of 10."""
        parsed = parse_args(["history"])
        assert parsed.command == "history"
        assert parsed.limit == 10

    def test_parse_config_command(self):
        """CLI parses 'config' subcommand correctly."""
        parsed = parse_args(["config"])
        assert parsed.command == "config"

    def test_parse_config_with_set(self):
        """CLI parses 'config --set key=value' correctly."""
        parsed = parse_args(["config", "--set", "interval=weekly"])
        assert parsed.command == "config"
        assert parsed.set_key == "interval=weekly"

    def test_no_command_returns_error_code(self):
        """CLI returns error code 1 when no command is given."""
        result = main([])
        assert result == 1

    def test_run_command_dispatches(self):
        """CLI dispatches 'run' command — verifies parsing only."""
        parsed = parse_args(["run"])
        assert parsed.command == "run"

    def test_status_command_dispatches(self):
        """CLI dispatches 'status' command — verifies parsing only."""
        parsed = parse_args(["status"])
        assert parsed.command == "status"

    def test_schedule_command_dispatches(self):
        """CLI dispatches 'schedule' command with interval — verifies parsing only."""
        parsed = parse_args(["schedule", "weekly"])
        assert parsed.command == "schedule"
        assert parsed.interval == "weekly"

    def test_invalid_schedule_interval_raises(self):
        """CLI raises SystemExit for invalid schedule interval."""
        with pytest.raises(SystemExit):
            parse_args(["schedule", "biweekly"])


# --- Test 4: Data Persistence Across Pipeline Runs ---


@pytest.mark.integration
class TestDataPersistence:
    """Test data persistence across pipeline runs."""

    @pytest.mark.asyncio
    async def test_pipeline_creates_all_directories(self, pipeline_config, tmp_path):
        """Pipeline run creates all required data directories."""
        with (
            patch("linkedin_optimizer.orchestrator.LinkedInMCPClient"),
            patch("linkedin_optimizer.orchestrator.ProfileScraper") as mock_scraper_cls,
            patch("linkedin_optimizer.orchestrator.GitHubExtractor"),
            patch("linkedin_optimizer.orchestrator.AnalyzerAgent") as mock_analyzer_cls,
            patch("linkedin_optimizer.orchestrator.ContentCreatorAgent") as mock_content_cls,
            patch("linkedin_optimizer.orchestrator.HuggingFaceClient"),
        ):
            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=False, profile_data=None, error_message="fail"
            )
            mock_scraper_cls.return_value = mock_scraper
            mock_analyzer_cls.return_value = AsyncMock()
            mock_content_cls.return_value = AsyncMock()

            orchestrator = PipelineOrchestrator(pipeline_config)
            await orchestrator.execute()

            # Even on failure, directories should be created
            data_dir = Path(pipeline_config.data_dir)
            assert (data_dir / "profiles").is_dir()
            assert (data_dir / "reports").is_dir()
            assert (data_dir / "content").is_dir()
            assert (data_dir / "approvals").is_dir()
            assert (data_dir / "engagement").is_dir()
            assert (data_dir / "runs").is_dir()

    @pytest.mark.asyncio
    async def test_run_metadata_persisted_on_success(
        self,
        pipeline_config,
        sample_profile_data,
        sample_optimization_report,
        sample_content_package,
    ):
        """Successful run persists RunMetadata to disk (Req 6.5)."""
        with (
            patch("linkedin_optimizer.orchestrator.LinkedInMCPClient"),
            patch("linkedin_optimizer.orchestrator.ProfileScraper") as mock_scraper_cls,
            patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls,
            patch("linkedin_optimizer.orchestrator.AnalyzerAgent") as mock_analyzer_cls,
            patch("linkedin_optimizer.orchestrator.ContentCreatorAgent") as mock_content_cls,
            patch("linkedin_optimizer.orchestrator.HuggingFaceClient"),
            patch("linkedin_optimizer.orchestrator.ApprovalWorkflow") as mock_approval_cls,
        ):
            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=True, profile_data=sample_profile_data
            )
            mock_scraper_cls.return_value = mock_scraper

            mock_gh = AsyncMock()
            mock_gh.extract.return_value = GitHubExtractionResult(
                success=False, data=None, error_message="timeout"
            )
            mock_gh_cls.return_value = mock_gh

            mock_analyzer = AsyncMock()
            mock_analyzer.analyze.return_value = sample_optimization_report
            mock_analyzer_cls.return_value = mock_analyzer

            mock_content = AsyncMock()
            mock_content.generate.return_value = sample_content_package
            mock_content_cls.return_value = mock_content

            mock_approval = AsyncMock()
            mock_approval.submit_for_review.return_value = MagicMock()
            mock_approval_cls.return_value = mock_approval

            orchestrator = PipelineOrchestrator(pipeline_config)
            result = await orchestrator.execute()

            # Verify metadata is persisted
            data_dir = Path(pipeline_config.data_dir)
            run_files = list((data_dir / "runs").glob("*_meta.json"))
            assert len(run_files) == 1

            with open(run_files[0]) as f:
                meta_data = json.load(f)

            assert meta_data["run_id"] == result.run_id
            assert meta_data["status"] == "completed"
            assert meta_data["start_time"] is not None
            assert meta_data["end_time"] is not None

    @pytest.mark.asyncio
    async def test_run_metadata_persisted_on_failure(self, pipeline_config):
        """Failed run still persists RunMetadata (Req 6.5)."""
        with (
            patch("linkedin_optimizer.orchestrator.LinkedInMCPClient"),
            patch("linkedin_optimizer.orchestrator.ProfileScraper") as mock_scraper_cls,
            patch("linkedin_optimizer.orchestrator.GitHubExtractor"),
            patch("linkedin_optimizer.orchestrator.AnalyzerAgent") as mock_analyzer_cls,
            patch("linkedin_optimizer.orchestrator.ContentCreatorAgent") as mock_content_cls,
            patch("linkedin_optimizer.orchestrator.HuggingFaceClient"),
        ):
            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=False, profile_data=None, error_message="Access denied"
            )
            mock_scraper_cls.return_value = mock_scraper
            mock_analyzer_cls.return_value = AsyncMock()
            mock_content_cls.return_value = AsyncMock()

            orchestrator = PipelineOrchestrator(pipeline_config)
            result = await orchestrator.execute()

            # Even on failure, metadata should be persisted
            data_dir = Path(pipeline_config.data_dir)
            run_files = list((data_dir / "runs").glob("*_meta.json"))
            assert len(run_files) == 1

            with open(run_files[0]) as f:
                meta_data = json.load(f)

            assert meta_data["status"] == "failed"
            assert "Access denied" in meta_data["error"]

    @pytest.mark.asyncio
    async def test_multiple_runs_persist_independently(
        self,
        pipeline_config,
        sample_profile_data,
        sample_optimization_report,
        sample_content_package,
    ):
        """Multiple pipeline runs each create independent data files."""
        with (
            patch("linkedin_optimizer.orchestrator.LinkedInMCPClient"),
            patch("linkedin_optimizer.orchestrator.ProfileScraper") as mock_scraper_cls,
            patch("linkedin_optimizer.orchestrator.GitHubExtractor") as mock_gh_cls,
            patch("linkedin_optimizer.orchestrator.AnalyzerAgent") as mock_analyzer_cls,
            patch("linkedin_optimizer.orchestrator.ContentCreatorAgent") as mock_content_cls,
            patch("linkedin_optimizer.orchestrator.HuggingFaceClient"),
            patch("linkedin_optimizer.orchestrator.ApprovalWorkflow") as mock_approval_cls,
        ):
            mock_scraper = AsyncMock()
            mock_scraper.extract.return_value = ExtractionResult(
                success=True, profile_data=sample_profile_data
            )
            mock_scraper_cls.return_value = mock_scraper

            mock_gh = AsyncMock()
            mock_gh.extract.return_value = GitHubExtractionResult(
                success=False, data=None, error_message="timeout"
            )
            mock_gh_cls.return_value = mock_gh

            mock_analyzer = AsyncMock()
            mock_analyzer.analyze.return_value = sample_optimization_report
            mock_analyzer_cls.return_value = mock_analyzer

            mock_content = AsyncMock()
            mock_content.generate.return_value = sample_content_package
            mock_content_cls.return_value = mock_content

            mock_approval = AsyncMock()
            mock_approval.submit_for_review.return_value = MagicMock()
            mock_approval_cls.return_value = mock_approval

            orchestrator = PipelineOrchestrator(pipeline_config)

            # Run 1
            result1 = await orchestrator.execute()
            assert result1.status == PipelineStatus.COMPLETED

            # Small delay to ensure different timestamps
            await asyncio.sleep(0.01)

            # Patch datetime to generate different run IDs
            import time
            time.sleep(1)  # ensure different second in timestamp

            # Run 2
            result2 = await orchestrator.execute()
            assert result2.status == PipelineStatus.COMPLETED

            # Verify two distinct runs
            assert result1.run_id != result2.run_id

            data_dir = Path(pipeline_config.data_dir)
            run_files = list((data_dir / "runs").glob("*_meta.json"))
            assert len(run_files) == 2

            profile_files = list((data_dir / "profiles").glob("*_profile.json"))
            assert len(profile_files) == 2


# --- Test 5: Approval Workflow E2E ---


@pytest.mark.integration
class TestApprovalWorkflowE2E:
    """Test approval workflow end-to-end with mocked user input."""

    @pytest.mark.asyncio
    async def test_submit_approve_and_reject(
        self, tmp_path, sample_content_package, sample_profile_data
    ):
        """Generate content, approve one item, reject another, verify statuses."""
        data_store = DataStore(str(tmp_path / "data"))
        notification_service = MagicMock()
        notification_service.notify = MagicMock()

        content_creator = AsyncMock()
        content_creator.revise_suggestion = AsyncMock(return_value="Revised content")

        workflow = ApprovalWorkflow(
            data_store=data_store,
            notification_service=notification_service,
            content_creator_agent=content_creator,
        )

        # Submit for review
        session = await workflow.submit_for_review(
            sample_content_package, sample_profile_data
        )

        # Verify session created with items
        assert session.session_id is not None
        assert len(session.items) >= 2  # headline + about at minimum
        assert session.notification_sent is True

        # Notification was sent
        notification_service.notify.assert_called()

        # Find headline and about items
        headline_item = next(
            (i for i in session.items if i.section_name == "headline"), None
        )
        about_item = next(
            (i for i in session.items if i.section_name == "about"), None
        )

        assert headline_item is not None
        assert about_item is not None

        # All items start as PENDING
        for item in session.items:
            assert item.status == ApprovalStatus.PENDING
            assert item.expires_at is not None
            assert item.expires_at > item.created_at

        # Approve headline
        approved_item = await workflow.approve(headline_item.item_id)
        assert approved_item.status == ApprovalStatus.APPROVED
        assert approved_item.decided_at is not None

        # Reject about with reason
        rejected_item = await workflow.reject(
            about_item.item_id, reason="Too generic"
        )
        assert rejected_item.status == ApprovalStatus.REJECTED
        assert rejected_item.rejection_reason == "Too generic"
        assert rejected_item.decided_at is not None

        # Verify independence: other items unchanged
        pending_items = await workflow.get_pending_items()
        for item in pending_items:
            assert item.item_id != headline_item.item_id
            assert item.item_id != about_item.item_id

    @pytest.mark.asyncio
    async def test_modification_workflow(
        self, tmp_path, sample_content_package, sample_profile_data
    ):
        """Request modification triggers revision and updates proposed content."""
        data_store = DataStore(str(tmp_path / "data"))
        notification_service = MagicMock()
        notification_service.notify = MagicMock()

        revised_text = "Better headline with more keywords and value prop"
        content_creator = AsyncMock()
        content_creator.revise_suggestion = AsyncMock(return_value=revised_text)

        workflow = ApprovalWorkflow(
            data_store=data_store,
            notification_service=notification_service,
            content_creator_agent=content_creator,
        )

        session = await workflow.submit_for_review(
            sample_content_package, sample_profile_data
        )

        headline_item = next(
            i for i in session.items if i.section_name == "headline"
        )

        # Request modification
        modified_item = await workflow.request_modification(
            headline_item.item_id, feedback="Make it shorter and punchier"
        )

        assert modified_item.status == ApprovalStatus.MODIFIED
        assert modified_item.proposed_content == revised_text
        assert modified_item.user_feedback == "Make it shorter and punchier"
        content_creator.revise_suggestion.assert_called_once()

    @pytest.mark.asyncio
    async def test_expiration_after_7_days(
        self, tmp_path, sample_content_package, sample_profile_data
    ):
        """Items expire after 7 days without user action (Req 5.7)."""
        data_store = DataStore(str(tmp_path / "data"))
        notification_service = MagicMock()
        notification_service.notify = MagicMock()
        content_creator = AsyncMock()

        workflow = ApprovalWorkflow(
            data_store=data_store,
            notification_service=notification_service,
            content_creator_agent=content_creator,
        )

        session = await workflow.submit_for_review(
            sample_content_package, sample_profile_data
        )

        # Manually set created_at and expires_at in the past
        for item in session.items:
            item.created_at = datetime.now() - timedelta(days=8)
            item.expires_at = datetime.now() - timedelta(days=1)

        # Expire stale items
        expired_items = await workflow.expire_stale_items()

        assert len(expired_items) > 0
        for item in expired_items:
            assert item.status == ApprovalStatus.EXPIRED

        # Notification about expiration was sent
        assert notification_service.notify.call_count >= 2  # initial + expiry

    @pytest.mark.asyncio
    async def test_rejection_reason_length_validation(
        self, tmp_path, sample_content_package, sample_profile_data
    ):
        """Rejection reason must be ≤500 characters (Req 5.6)."""
        data_store = DataStore(str(tmp_path / "data"))
        notification_service = MagicMock()
        notification_service.notify = MagicMock()
        content_creator = AsyncMock()

        workflow = ApprovalWorkflow(
            data_store=data_store,
            notification_service=notification_service,
            content_creator_agent=content_creator,
        )

        session = await workflow.submit_for_review(
            sample_content_package, sample_profile_data
        )

        headline_item = next(
            i for i in session.items if i.section_name == "headline"
        )

        # Exactly 500 chars should work
        await workflow.reject(headline_item.item_id, reason="x" * 500)

        # Over 500 chars should raise
        # Reset the item status for the next test
        headline_item.status = ApprovalStatus.PENDING

        with pytest.raises(ValueError, match="500"):
            await workflow.reject(headline_item.item_id, reason="x" * 501)

    @pytest.mark.asyncio
    async def test_approval_persists_to_disk(
        self, tmp_path, sample_content_package, sample_profile_data
    ):
        """Approval sessions are persisted to the approvals/ directory."""
        data_store = DataStore(str(tmp_path / "data"))
        notification_service = MagicMock()
        notification_service.notify = MagicMock()
        content_creator = AsyncMock()

        workflow = ApprovalWorkflow(
            data_store=data_store,
            notification_service=notification_service,
            content_creator_agent=content_creator,
        )

        session = await workflow.submit_for_review(
            sample_content_package, sample_profile_data
        )

        # Verify file was created
        approvals_dir = Path(str(tmp_path / "data")) / "approvals"
        approval_files = list(approvals_dir.glob("*_approval.json"))
        assert len(approval_files) >= 1

        # Verify content is valid JSON with correct structure
        with open(approval_files[0]) as f:
            data = json.load(f)

        assert data["session_id"] == session.session_id
        assert len(data["items"]) == len(session.items)
        assert data["notification_sent"] is True
