"""Unit tests for the PipelineScheduler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_optimizer.models import ScheduleInterval, PipelineStatus, RunMetadata
from linkedin_optimizer.scheduler import PipelineScheduler, _PIPELINE_JOB_ID


@pytest.fixture
def mock_orchestrator():
    """Create a mock PipelineOrchestrator."""
    orchestrator = MagicMock()
    orchestrator.trigger_on_demand = AsyncMock(
        return_value=RunMetadata(
            run_id="run_2025-01-15_080000",
            start_time=None,
            end_time=None,
            status=PipelineStatus.COMPLETED,
            summary="OK",
            error=None,
        )
    )
    return orchestrator


@pytest.fixture
def scheduler(mock_orchestrator):
    """Create a PipelineScheduler instance."""
    return PipelineScheduler(mock_orchestrator)


class TestPipelineSchedulerInit:
    """Tests for scheduler initialization."""

    def test_initial_state(self, scheduler):
        """Scheduler should start with no interval and not running."""
        assert scheduler.current_interval is None
        assert scheduler.is_running is False

    def test_stores_orchestrator(self, scheduler, mock_orchestrator):
        """Scheduler should store the orchestrator reference."""
        assert scheduler._orchestrator is mock_orchestrator

    def test_default_hour(self, scheduler):
        """Default run hour should be 8."""
        assert scheduler._default_hour == 8

    def test_custom_hour(self, mock_orchestrator):
        """Should accept a custom default_hour."""
        sched = PipelineScheduler(mock_orchestrator, default_hour=6)
        assert sched._default_hour == 6


class TestScheduleMethod:
    """Tests for the schedule() method."""

    def test_schedule_daily(self, scheduler):
        """Should configure a daily cron trigger."""
        scheduler.schedule(ScheduleInterval.DAILY)
        assert scheduler.current_interval == ScheduleInterval.DAILY
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None

    def test_schedule_weekly(self, scheduler):
        """Should configure a weekly cron trigger (Monday)."""
        scheduler.schedule(ScheduleInterval.WEEKLY)
        assert scheduler.current_interval == ScheduleInterval.WEEKLY
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None

    def test_schedule_monthly(self, scheduler):
        """Should configure a monthly cron trigger (1st of month)."""
        scheduler.schedule(ScheduleInterval.MONTHLY)
        assert scheduler.current_interval == ScheduleInterval.MONTHLY
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None

    def test_reschedule_replaces_existing_job(self, scheduler):
        """Rescheduling should replace the existing job."""
        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.schedule(ScheduleInterval.WEEKLY)
        assert scheduler.current_interval == ScheduleInterval.WEEKLY
        # Only one job should exist
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None


class TestPauseResume:
    """Tests for pause() and resume() methods (Req 6.6)."""

    def test_pause_scheduled_job(self, scheduler):
        """Pausing should pause the scheduled job."""
        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.pause()
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None
        # APScheduler paused jobs have next_run_time set to None
        assert job.next_run_time is None

    def test_resume_paused_job(self, scheduler):
        """Resuming should restore the scheduled job."""
        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.pause()
        scheduler.resume()
        job = scheduler._scheduler.get_job(_PIPELINE_JOB_ID)
        assert job is not None
        # After resume, next_run_time should be set
        assert job.next_run_time is not None

    def test_pause_without_job_no_error(self, scheduler):
        """Pausing with no job should not raise an error."""
        scheduler.pause()  # Should not raise

    def test_resume_without_job_no_error(self, scheduler):
        """Resuming with no job should not raise an error."""
        scheduler.resume()  # Should not raise


class TestStartStop:
    """Tests for start() and stop() methods."""

    @pytest.mark.asyncio
    async def test_start_sets_running(self, scheduler):
        """Starting should set the scheduler to running."""
        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.start()
        assert scheduler.is_running is True
        scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_clears_running(self, scheduler):
        """Stopping should set the scheduler to not running after event loop yields."""
        import asyncio

        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.start()
        scheduler.stop()
        # AsyncIOScheduler shutdown is asynchronous; yield to the event loop
        await asyncio.sleep(0.1)
        assert scheduler.is_running is False

    @pytest.mark.asyncio
    async def test_start_twice_no_error(self, scheduler):
        """Starting an already running scheduler should not error."""
        scheduler.schedule(ScheduleInterval.DAILY)
        scheduler.start()
        scheduler.start()  # Should not raise
        assert scheduler.is_running is True
        scheduler.stop()

    def test_stop_when_not_running_no_error(self, scheduler):
        """Stopping a non-running scheduler should not error."""
        scheduler.stop()  # Should not raise


class TestTriggerPipeline:
    """Tests for the _trigger_pipeline callback."""

    @pytest.mark.asyncio
    async def test_trigger_calls_orchestrator(self, scheduler, mock_orchestrator):
        """The trigger callback should call orchestrator.trigger_on_demand()."""
        await scheduler._trigger_pipeline()
        mock_orchestrator.trigger_on_demand.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_handles_exception(self, scheduler, mock_orchestrator):
        """The trigger callback should handle orchestrator exceptions gracefully."""
        mock_orchestrator.trigger_on_demand = AsyncMock(
            side_effect=Exception("Pipeline error")
        )
        # Should not raise
        await scheduler._trigger_pipeline()


class TestCronTriggerConfiguration:
    """Tests for cron trigger building."""

    def test_daily_trigger_hour(self, scheduler):
        """Daily trigger should fire at the configured hour."""
        trigger = scheduler._build_cron_trigger(ScheduleInterval.DAILY)
        # CronTrigger fields check
        assert str(trigger.fields[5]) == "8"  # hour field

    def test_weekly_trigger_day_and_hour(self, scheduler):
        """Weekly trigger should fire on Monday at the configured hour."""
        trigger = scheduler._build_cron_trigger(ScheduleInterval.WEEKLY)
        assert str(trigger.fields[4]) == "0"  # day_of_week field (0=Monday)
        assert str(trigger.fields[5]) == "8"  # hour field

    def test_monthly_trigger_day_and_hour(self, scheduler):
        """Monthly trigger should fire on the 1st at the configured hour."""
        trigger = scheduler._build_cron_trigger(ScheduleInterval.MONTHLY)
        assert str(trigger.fields[2]) == "1"  # day field (index 2)
        assert str(trigger.fields[5]) == "8"  # hour field

    def test_custom_hour_reflected_in_trigger(self, mock_orchestrator):
        """Custom default_hour should be reflected in the trigger."""
        sched = PipelineScheduler(mock_orchestrator, default_hour=14)
        trigger = sched._build_cron_trigger(ScheduleInterval.DAILY)
        assert str(trigger.fields[5]) == "14"  # hour field
