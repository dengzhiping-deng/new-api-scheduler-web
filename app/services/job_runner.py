from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..config_store import ConfigStore
from ..core.automation import AutomationRunner
from ..models import JobRun, JobSummary, JobType, RunStatus
from ..storage import RunStore


class ConcurrentRunError(RuntimeError):
    pass


class JobService:
    def __init__(self, config_store: ConfigStore, run_store: RunStore, data_dir: Path):
        self.config_store = config_store
        self.run_store = run_store
        self.data_dir = data_dir
        self.log_dir = data_dir / "logs"
        self.lock_path = data_dir / "run.lock"
        self._lock = threading.Lock()
        self._current_run_id: str | None = None
        self.log_dir.mkdir(parents=True, exist_ok=True)

    @property
    def current_run_id(self) -> str | None:
        return self._current_run_id

    def _write_lock(self) -> None:
        self.lock_path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")

    def _clear_lock(self) -> None:
        if self.lock_path.exists():
            self.lock_path.unlink()

    def _stale_lock_exists(self, ttl_minutes: int) -> bool:
        if not self.lock_path.exists():
            return False
        age_seconds = datetime.now(UTC).timestamp() - self.lock_path.stat().st_mtime
        return age_seconds > ttl_minutes * 60

    def _prepare_run(self, job_type: JobType, trigger: str) -> JobRun:
        run_id = uuid.uuid4().hex
        log_file = self.log_dir / f"{run_id}.log"
        run = JobRun(
            run_id=run_id,
            job_type=job_type,
            status=RunStatus.RUNNING,
            trigger=trigger,
            started_at=datetime.now(UTC),
            log_file=str(log_file),
        )
        config = self.config_store.load()
        self.run_store.append(run, config.run_history_limit)
        return run

    def cleanup_old_logs(self, retention_days: int | None = None) -> None:
        configured_days = retention_days if retention_days is not None else self.config_store.load().log_retention_days
        cutoff = datetime.now(UTC) - timedelta(days=configured_days)
        for path in self.log_dir.glob("*.log"):
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified_at < cutoff:
                path.unlink(missing_ok=True)

    def cleanup_old_runs(self) -> None:
        config = self.config_store.load()
        self.run_store.cleanup_old_runs(
            retention_days=config.run_retention_days,
            limit=config.run_history_limit,
        )

    def run_job(self, job_type: JobType, trigger: str = "manual") -> JobRun:
        config = self.config_store.load()
        if self._stale_lock_exists(config.lock_ttl_minutes):
            self._clear_lock()

        if not self._lock.acquire(blocking=False):
            raise ConcurrentRunError("another job is already running")

        run = self._prepare_run(job_type, trigger)
        self._current_run_id = run.run_id
        self._write_lock()
        try:
            runner = AutomationRunner(config=config, log_path=Path(run.log_file))
            summary, decisions, metadata = self._execute(runner, job_type)
            run.summary = summary
            run.decisions = decisions
            run.metadata = metadata
            run.status = self._derive_status(job_type, summary)
            return self._finalize(run)
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error = str(exc)
            Path(run.log_file).parent.mkdir(parents=True, exist_ok=True)
            Path(run.log_file).write_text(str(exc) + "\n", encoding="utf-8")
            return self._finalize(run)
        finally:
            self._current_run_id = None
            self._clear_lock()
            self._lock.release()

    def validate_config(self) -> None:
        config = self.config_store.load()
        runner = AutomationRunner(config=config, log_path=self.log_dir / "validation.log")
        runner.validate_connection()
        self.cleanup_old_runs()
        self.cleanup_old_logs()

    def record_skipped_run(self, job_type: JobType, trigger: str, reason: str) -> JobRun:
        run = self._prepare_run(job_type, trigger)
        run.status = RunStatus.SKIPPED
        run.error = reason
        run.finished_at = datetime.now(UTC)
        run.duration_seconds = 0.0
        config = self.config_store.load()
        self.run_store.replace(run, config.run_history_limit)
        self.cleanup_old_runs()
        Path(run.log_file).write_text(reason + "\n", encoding="utf-8")
        self.cleanup_old_logs()
        return run

    def _execute(self, runner: AutomationRunner, job_type: JobType):
        if job_type == JobType.CHECK:
            summary, decisions, stats = runner.run_check()
            return summary, decisions, {
                "check_executed": True,
                "enable_executed": False,
                "check_exit_code": 0,
                "enable_exit_code": None,
                "check_summary": summary.model_dump(mode="json"),
                "enable_summary": None,
                "check_stats": stats,
                "enable_stats": None,
            }
        if job_type == JobType.ENABLE:
            summary, decisions, stats = runner.run_enable()
            return summary, decisions, {
                "check_executed": False,
                "enable_executed": True,
                "check_exit_code": None,
                "enable_exit_code": 0,
                "check_summary": None,
                "enable_summary": summary.model_dump(mode="json"),
                "check_stats": None,
                "enable_stats": stats,
            }

        check_summary, check_decisions, check_stats = runner.run_check()
        should_enable = (
            check_summary.suggest_reenable > 0
            or check_summary.weekly_window_grace > 0
            or check_summary.rate_limit_grace > 0
        )
        if not should_enable:
            return check_summary, check_decisions, {
                "check_executed": True,
                "enable_executed": False,
                "check_exit_code": 0,
                "enable_exit_code": None,
                "check_summary": check_summary.model_dump(mode="json"),
                "enable_summary": None,
                "check_stats": check_stats,
                "enable_stats": None,
            }

        enable_summary, enable_decisions, enable_stats = runner.run_enable()
        merged = JobSummary(
            total=check_summary.total,
            codex=check_summary.codex,
            non_codex=check_summary.non_codex,
            suggest_reenable=check_summary.suggest_reenable,
            weekly_window_blocked=check_summary.weekly_window_blocked,
            weekly_window_grace=check_summary.weekly_window_grace,
            short_window_blocked=check_summary.short_window_blocked,
            rate_limit_blocked=check_summary.rate_limit_blocked,
            rate_limit_grace=check_summary.rate_limit_grace,
            not_allowed=check_summary.not_allowed,
            non_codex_review=check_summary.non_codex_review,
            usage_error=check_summary.usage_error,
            usage_error_401=check_summary.usage_error_401,
            usage_error_402=check_summary.usage_error_402,
            usage_error_other=check_summary.usage_error_other,
            success=enable_summary.success,
            failed=enable_summary.failed,
            skipped=enable_summary.skipped,
            skipped_weekly_window_blocked=enable_summary.skipped_weekly_window_blocked,
            skipped_short_window_blocked=enable_summary.skipped_short_window_blocked,
            skipped_rate_limit_blocked=enable_summary.skipped_rate_limit_blocked,
            skipped_not_allowed=enable_summary.skipped_not_allowed,
            skipped_usage_401=enable_summary.skipped_usage_401,
            skipped_usage_402=enable_summary.skipped_usage_402,
            skipped_max_enable=enable_summary.skipped_max_enable,
            dry_run_skipped=enable_summary.dry_run_skipped,
            dry_run=enable_summary.dry_run,
        )
        return merged, check_decisions + enable_decisions, {
            "check_executed": True,
            "enable_executed": True,
            "check_exit_code": 0,
            "enable_exit_code": 0,
            "check_summary": check_summary.model_dump(mode="json"),
            "enable_summary": enable_summary.model_dump(mode="json"),
            "check_stats": check_stats,
            "enable_stats": enable_stats,
        }

    def _derive_status(self, job_type: JobType, summary: JobSummary) -> RunStatus:
        if summary.failed > 0:
            return RunStatus.PARTIAL if summary.success > 0 or summary.skipped > 0 else RunStatus.FAILED
        if job_type == JobType.ENABLE and summary.success == 0 and summary.skipped > 0:
            return RunStatus.SUCCESS
        return RunStatus.SUCCESS

    def _finalize(self, run: JobRun) -> JobRun:
        run.finished_at = datetime.now(UTC)
        run.duration_seconds = (run.finished_at - run.started_at).total_seconds()
        config = self.config_store.load()
        self.run_store.replace(run, config.run_history_limit)
        self.cleanup_old_runs()
        self.cleanup_old_logs()
        return run
