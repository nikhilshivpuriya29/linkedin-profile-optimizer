"""Pipeline Scheduler for the LinkedIn Profile Optimizer.

Provides cron-based scheduling using APScheduler's AsyncIOScheduler
for daily, weekly, or monthly pipeline execution.

Implements Requirements 6.2, 6.6, 6.7.
"""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from linkedin_optimizer.models import ScheduleInterval
from linkedin_optimizer.orchestrator import PipelineOrchestrator

logger = logging.getLogger(__name__)

# Job ID constant used for the scheduled pipeline job
_PIPELINE_JOB_ID = "pipeline_scheduled_run"


class PipelineScheduler:
    """Cron-based scheduler for periodic pipeline execution.

    Uses APScheduler's AsyncIOScheduler to trigger pipeline runs at
    configurable intervals (daily, weekly, monthly). Delegates concurrency
    handling to the orchestrator's trigger_on_demand method, which queues
    runs if the pipeline is already executing.

    Implements Requirements 6.2, 6.6, 6.7.
    """

    def __init__(
        self, orchestrator: PipelineOrchestrator, default_hour: int = 8
    ) -> None:
        """Initialize the scheduler with a pipeline orchestrator.

        Args:
            orchestrator: The PipelineOrchestrator instance to trigger on schedule.
            default_hour: Hour of the day (0-23) at which scheduled runs execute.
                          Defaults to 8 (8 AM).
        """
        self._orchestrator = orchestrator
        self._default_hour = default_hour
        self._scheduler = AsyncIOScheduler()
        self._current_interval: Optional[ScheduleInterval] = None

    def schedule(self, interval: ScheduleInterval) -> None:
        """Configure cron-based scheduling at the specified interval.

        Removes any existing scheduled job before adding the new one.

        Intervals:
            - DAILY: runs every day at the configured hour (default 8 AM)
            - WEEKLY: runs every Monday at the configured hour
            - MONTHLY: runs on the 1st of each month at the configured hour

        Args:
            interval: The ScheduleInterval enum value (DAILY, WEEKLY, MONTHLY).
        """
        # Remove existing job if any
        if self._scheduler.get_job(_PIPELINE_JOB_ID):
            self._scheduler.remove_job(_PIPELINE_JOB_ID)

        trigger = self._build_cron_trigger(interval)

        self._scheduler.add_job(
            self._trigger_pipeline,
            trigger=trigger,
            id=_PIPELINE_JOB_ID,
            name=f"Pipeline scheduled run ({interval.value})",
            replace_existing=True,
        )

        self._current_interval = interval
        logger.info("Scheduled pipeline execution: %s at hour %d", interval.value, self._default_hour)

    def _build_cron_trigger(self, interval: ScheduleInterval) -> CronTrigger:
        """Build an APScheduler CronTrigger for the given interval.

        Args:
            interval: The schedule interval to convert to a cron trigger.

        Returns:
            CronTrigger configured for the specified interval.
        """
        if interval == ScheduleInterval.DAILY:
            return CronTrigger(hour=self._default_hour, minute=0)
        elif interval == ScheduleInterval.WEEKLY:
            # day_of_week=0 is Monday in APScheduler
            return CronTrigger(day_of_week=0, hour=self._default_hour, minute=0)
        elif interval == ScheduleInterval.MONTHLY:
            return CronTrigger(day=1, hour=self._default_hour, minute=0)
        else:
            raise ValueError(f"Unsupported schedule interval: {interval}")

    async def _trigger_pipeline(self) -> None:
        """Callback invoked by the scheduler on each trigger.

        Delegates to the orchestrator's trigger_on_demand() which handles
        concurrency: if a run is already in progress, it queues the new
        trigger and executes after the current run completes (Req 6.7).
        """
        logger.info("Scheduled trigger fired. Invoking pipeline...")
        try:
            metadata = await self._orchestrator.trigger_on_demand()
            logger.info(
                "Scheduled run completed: %s (status=%s)",
                metadata.run_id,
                metadata.status.value,
            )
        except Exception as e:
            logger.error("Scheduled pipeline execution failed: %s", str(e))

    def pause(self) -> None:
        """Pause the scheduled job without removing it.

        The job remains configured and can be resumed later (Req 6.6).
        """
        job = self._scheduler.get_job(_PIPELINE_JOB_ID)
        if job:
            job.pause()
            logger.info("Scheduled pipeline execution paused.")
        else:
            logger.warning("No scheduled job to pause.")

    def resume(self) -> None:
        """Resume a previously paused scheduled job (Req 6.6)."""
        job = self._scheduler.get_job(_PIPELINE_JOB_ID)
        if job:
            job.resume()
            logger.info("Scheduled pipeline execution resumed.")
        else:
            logger.warning("No scheduled job to resume.")

    def start(self) -> None:
        """Start the scheduler event loop.

        Must be called after schedule() to begin triggering executions.
        """
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started.")
        else:
            logger.warning("Scheduler is already running.")

    def stop(self) -> None:
        """Stop the scheduler, shutting down all pending jobs."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")
        else:
            logger.warning("Scheduler is not running.")

    @property
    def current_interval(self) -> Optional[ScheduleInterval]:
        """Return the currently configured schedule interval, if any."""
        return self._current_interval

    @property
    def is_running(self) -> bool:
        """Return whether the scheduler event loop is active."""
        return self._scheduler.running
