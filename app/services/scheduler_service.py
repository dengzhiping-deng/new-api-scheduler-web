from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config_store import ConfigStore
from ..models import JobType, SchedulerStatus
from .job_runner import ConcurrentRunError, JobService


class SchedulerService:
    def __init__(self, config_store: ConfigStore, job_service: JobService):
        self.config_store = config_store
        self.job_service = job_service
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True
        self.reload()

    def stop(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    def reload(self) -> None:
        config = self.config_store.load()
        self.scheduler.remove_all_jobs()
        if not config.schedule_enabled:
            return
        self.scheduler.add_job(
            self._run_scheduled_job,
            trigger=IntervalTrigger(minutes=config.schedule_interval_minutes),
            id="scheduled-check-enable",
            replace_existing=True,
            max_instances=1,
        )

    def _run_scheduled_job(self) -> None:
        config = self.config_store.load()
        job_type = JobType.CHECK_AND_ENABLE if config.auto_reenable_enabled else JobType.CHECK
        try:
            self.job_service.run_job(job_type=job_type, trigger="schedule")
        except ConcurrentRunError:
            self.job_service.record_skipped_run(
                job_type=job_type,
                trigger="schedule",
                reason="skipped_due_to_running",
            )

    def status(self) -> SchedulerStatus:
        config = self.config_store.load()
        job = self.scheduler.get_job("scheduled-check-enable")
        return SchedulerStatus(
            started=self.started,
            schedule_enabled=config.schedule_enabled,
            interval_minutes=config.schedule_interval_minutes if config.schedule_enabled else None,
            auto_reenable_enabled=config.auto_reenable_enabled,
            next_run_time=(job.next_run_time if job else None),
            currently_running=self.job_service.current_run_id is not None,
        )
