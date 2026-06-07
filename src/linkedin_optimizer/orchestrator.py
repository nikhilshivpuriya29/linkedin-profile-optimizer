"""Pipeline Orchestrator for the LinkedIn Profile Optimizer.

Coordinates sequential execution of pipeline stages:
ProfileScraper → AnalyzerAgent → ContentCreatorAgent → ApprovalWorkflow

Implements Requirements 6.1, 6.3, 6.4, 6.5, 6.7, 7.4.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from linkedin_optimizer.config import HFModelConfig, PipelineConfig
from linkedin_optimizer.models import (
    ContentPackage,
    GitHubData,
    OptimizationReport,
    PipelineStatus,
    ProfileData,
    RunMetadata,
)
from linkedin_optimizer.persistence.data_store import DataStore
from linkedin_optimizer.integrations.hf_client import HuggingFaceClient
from linkedin_optimizer.scrapers.profile_scraper import ProfileScraper
from linkedin_optimizer.scrapers.linkedin_mcp_client import LinkedInMCPClient
from linkedin_optimizer.scrapers.github_extractor import GitHubExtractor
from linkedin_optimizer.agents.analyzer_agent import AnalyzerAgent
from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent
from linkedin_optimizer.approval.workflow import ApprovalWorkflow

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Coordinates sequential execution of pipeline stages.

    Manages pipeline lifecycle including on-demand triggers, run queuing,
    status tracking, and metadata logging. Enforces strict stage ordering
    and halts on any stage failure.

    Implements Requirements 6.1, 6.3, 6.4, 6.5, 6.7, 7.4.
    """

    def __init__(self, config: PipelineConfig) -> None:
        """Initialize all pipeline components from configuration.

        Args:
            config: Pipeline configuration containing all service settings.
        """
        self._config = config
        self._status = PipelineStatus.IDLE
        self._lock = asyncio.Lock()
        self._run_queue: asyncio.Queue[str] = asyncio.Queue()
        self._current_run_id: Optional[str] = None

        # Initialize data store
        self._data_store = DataStore(config.data_dir)

        # Initialize LinkedIn MCP client and profile scraper
        self._mcp_client = LinkedInMCPClient(mcp_server_config={})
        self._profile_scraper = ProfileScraper(self._mcp_client, max_retries=config.hf_max_retries)

        # Initialize HuggingFace clients for analyzer and content creator
        analyzer_hf_config = HFModelConfig(
            model_id=config.analyzer_model_id,
            fallback_model_id=config.fallback_model_id,
            api_token=config.hf_api_token,
            timeout_seconds=config.hf_timeout_seconds,
            max_retries=config.hf_max_retries,
        )
        content_hf_config = HFModelConfig(
            model_id=config.content_model_id,
            fallback_model_id=config.fallback_model_id,
            api_token=config.hf_api_token,
            timeout_seconds=config.hf_timeout_seconds,
            max_retries=config.hf_max_retries,
        )

        self._analyzer_hf_client = HuggingFaceClient(analyzer_hf_config)
        self._content_hf_client = HuggingFaceClient(content_hf_config)

        # Initialize agents
        self._analyzer_agent = AnalyzerAgent(
            model_id=config.analyzer_model_id,
            fallback_model_id=config.fallback_model_id,
            hf_client=self._analyzer_hf_client,
        )
        self._content_creator_agent = ContentCreatorAgent(
            model_id=config.content_model_id,
            fallback_model_id=config.fallback_model_id,
            hf_client=self._content_hf_client,
        )

        # Initialize approval workflow
        self._approval_workflow = ApprovalWorkflow(
            data_store=self._data_store,
            notification_service=None,
            content_creator_agent=self._content_creator_agent,
        )

    def _generate_run_id(self) -> str:
        """Generate a unique run ID using timestamp format.

        Returns:
            Run ID in format: run_YYYY-MM-DD_HHMMSS
        """
        now = datetime.now()
        return f"run_{now.strftime('%Y-%m-%d_%H%M%S')}"

    def get_status(self) -> PipelineStatus:
        """Return current pipeline status.

        Returns:
            Current PipelineStatus enum value.
        """
        return self._status

    async def execute(self) -> RunMetadata:
        """Execute the full pipeline in strict sequential order.

        Stages:
        1. ProfileScraper — extract LinkedIn profile data
        2. GitHubExtractor — extract GitHub data (graceful degradation on failure)
        3. AnalyzerAgent — analyze and score profile
        4. ContentCreatorAgent — generate optimized content
        5. ApprovalWorkflow — submit for user review

        Halts on any stage failure (except GitHub which degrades gracefully).
        Logs RunMetadata after each run; only marks completed after metadata is logged.

        Returns:
            RunMetadata with run details including status and timing.
        """
        run_id = self._generate_run_id()
        self._current_run_id = run_id
        self._status = PipelineStatus.RUNNING
        start_time = datetime.now()

        logger.info("Pipeline execution started: %s", run_id)

        try:
            # Stage 1: Profile extraction (Req 6.3 - scraper first)
            logger.info("[%s] Stage 1: Extracting LinkedIn profile...", run_id)
            extraction_result = await self._profile_scraper.extract(
                self._config.linkedin_profile_url
            )

            if not extraction_result.success:
                error_msg = (
                    f"Profile extraction failed: {extraction_result.error_message}"
                )
                logger.error("[%s] %s", run_id, error_msg)
                return await self._finalize_run(
                    run_id, start_time, PipelineStatus.FAILED, error=error_msg
                )

            profile_data: ProfileData = extraction_result.profile_data  # type: ignore[assignment]

            # Save profile snapshot
            self._data_store.save_profile_snapshot(profile_data, run_id)

            # Stage 2: GitHub extraction (Req 7.4 - graceful degradation)
            github_data: Optional[GitHubData] = None
            if self._config.github_username:
                logger.info("[%s] Stage 2: Extracting GitHub data...", run_id)
                try:
                    extractor = GitHubExtractor(
                        username=self._config.github_username, timeout=15
                    )
                    github_result = await extractor.extract()
                    if github_result.success and github_result.data:
                        github_data = github_result.data
                        logger.info(
                            "[%s] GitHub extraction successful (partial=%s)",
                            run_id,
                            github_result.partial,
                        )
                    else:
                        logger.warning(
                            "[%s] GitHub extraction failed: %s. Continuing with LinkedIn-only.",
                            run_id,
                            github_result.error_message,
                        )
                except Exception as e:
                    logger.warning(
                        "[%s] GitHub unavailable: %s. Continuing with LinkedIn-only.",
                        run_id,
                        str(e),
                    )
            else:
                logger.info("[%s] No GitHub username configured, skipping.", run_id)

            # Stage 3: Analysis (Req 6.3 - analyzer second, Req 6.4 - halt on failure)
            logger.info("[%s] Stage 3: Analyzing profile...", run_id)
            try:
                optimization_report: OptimizationReport = (
                    await self._analyzer_agent.analyze(profile_data, github_data)
                )
            except Exception as e:
                error_msg = f"Analyzer agent failed: {str(e)}"
                logger.error("[%s] %s", run_id, error_msg)
                return await self._finalize_run(
                    run_id, start_time, PipelineStatus.FAILED, error=error_msg
                )

            # Save optimization report
            self._data_store.save_optimization_report(optimization_report, run_id)

            # Stage 4: Content generation (Req 6.3 - content creator third)
            logger.info("[%s] Stage 4: Generating content...", run_id)
            try:
                content_package: ContentPackage = (
                    await self._content_creator_agent.generate(
                        optimization_report, profile_data, github_data
                    )
                )
            except Exception as e:
                error_msg = f"Content creator agent failed: {str(e)}"
                logger.error("[%s] %s", run_id, error_msg)
                return await self._finalize_run(
                    run_id, start_time, PipelineStatus.FAILED, error=error_msg
                )

            # Save content package
            self._data_store.save_content_package(content_package, run_id)

            # Stage 5: Approval workflow (Req 6.3 - approval gate last)
            logger.info("[%s] Stage 5: Submitting for approval...", run_id)
            try:
                await self._approval_workflow.submit_for_review(
                    content_package, profile_data
                )
            except Exception as e:
                error_msg = f"Approval workflow failed: {str(e)}"
                logger.error("[%s] %s", run_id, error_msg)
                return await self._finalize_run(
                    run_id, start_time, PipelineStatus.FAILED, error=error_msg
                )

            # All stages completed successfully
            summary = (
                f"Pipeline completed. Overall score: {optimization_report.overall_score}/100. "
                f"GitHub data: {'included' if github_data else 'not available'}."
            )
            logger.info("[%s] %s", run_id, summary)

            return await self._finalize_run(
                run_id, start_time, PipelineStatus.COMPLETED, summary=summary
            )

        except Exception as e:
            error_msg = f"Unexpected pipeline error: {str(e)}"
            logger.error("[%s] %s", run_id, error_msg)
            return await self._finalize_run(
                run_id, start_time, PipelineStatus.FAILED, error=error_msg
            )

    async def _finalize_run(
        self,
        run_id: str,
        start_time: datetime,
        status: PipelineStatus,
        summary: Optional[str] = None,
        error: Optional[str] = None,
    ) -> RunMetadata:
        """Finalize a pipeline run by logging metadata and updating status.

        Only marks the run as completed/failed AFTER metadata is successfully
        logged (Req 6.5).

        Args:
            run_id: The unique run identifier.
            start_time: When the run started.
            status: Final status of the run.
            summary: Optional summary of findings.
            error: Optional error message if failed.

        Returns:
            RunMetadata for the completed run.
        """
        end_time = datetime.now()
        metadata = RunMetadata(
            run_id=run_id,
            start_time=start_time,
            end_time=end_time,
            status=status,
            summary=summary,
            error=error,
        )

        # Log metadata via DataStore (Req 6.5 - only mark completed after metadata logged)
        self._data_store.save_run_metadata(metadata)

        # Now update pipeline status
        self._status = PipelineStatus.IDLE
        self._current_run_id = None

        logger.info(
            "[%s] Run finalized: status=%s, duration=%.1fs",
            run_id,
            status.value,
            (end_time - start_time).total_seconds(),
        )

        return metadata

    async def trigger_on_demand(self) -> RunMetadata:
        """Trigger immediate pipeline execution if not already running.

        If the pipeline is currently running, queues the request and waits
        for it to execute (Req 6.7).

        Returns:
            RunMetadata from the executed run.
        """
        if self._lock.locked():
            # Pipeline is already running, queue this trigger (Req 6.7)
            logger.info("Pipeline already running. Queuing on-demand trigger.")
            position = self.enqueue_run()
            logger.info("Queued at position %d. Waiting for execution...", position)
            # Wait for the lock to become available, then execute
            async with self._lock:
                return await self.execute()
        else:
            # Execute immediately (Req 6.1)
            async with self._lock:
                return await self.execute()

    def enqueue_run(self) -> int:
        """Queue a concurrent trigger and return its position.

        Adds a run request to the internal queue when the pipeline
        is already running.

        Returns:
            Queue position (1-based) of the enqueued run.
        """
        run_id = self._generate_run_id()
        self._run_queue.put_nowait(run_id)
        position = self._run_queue.qsize()
        logger.info("Run enqueued: %s at position %d", run_id, position)
        return position
