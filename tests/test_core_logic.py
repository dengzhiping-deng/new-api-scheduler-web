import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config_store import AuthStore, ConfigStore
from app.core.automation import classify_codex_usage
from app.models import AppConfig, ConfigUpdate, JobRun, JobSummary, JobType, RunStatus
from app.services.job_runner import JobService
from app.storage import RunStore


def test_classify_weekly_blocked():
    suggestion, reason, details = classify_codex_usage(
        {
            "rate_limit": {
                "allowed": False,
                "limit_reached": True,
                "primary_window": {"limit_window_seconds": 18000, "used_percent": 100, "reset_after_seconds": 120},
                "secondary_window": {"limit_window_seconds": 604800, "used_percent": 100, "reset_after_seconds": 3600},
            }
        }
    )
    assert reason == "weekly_window_blocked"
    assert "周窗口" in suggestion
    assert details["weekly_reset_after_seconds"] == 3600


def test_classify_rate_limit_grace():
    suggestion, reason, _ = classify_codex_usage(
        {
            "rate_limit": {
                "allowed": False,
                "limit_reached": True,
                "primary_window": {"limit_window_seconds": 18000, "used_percent": 20, "reset_after_seconds": 10},
                "secondary_window": {"limit_window_seconds": 604800, "used_percent": 80, "reset_after_seconds": 10},
            }
        }
    )
    assert reason == "rate_limit_grace"
    assert "建议恢复" in suggestion


def test_config_store_preserves_password(tmp_path: Path):
    store = ConfigStore(tmp_path / "config.json")
    store.save(
        AppConfig(
            new_api_username="u",
            new_api_password="secret",
            log_page_size=123,
            run_history_limit=456,
        )
    )
    updated = store.update(
        ConfigUpdate(
            request_timeout=15,
            max_enable_per_run=10,
            dry_run=True,
            deny_channel_ids=[],
            schedule_enabled=True,
            auto_reenable_enabled=True,
            schedule_interval_minutes=10,
            log_retention_days=3,
            run_retention_days=3,
            lock_ttl_minutes=30,
        )
    )
    assert updated.new_api_password == "secret"
    assert updated.new_api_username == "u"
    assert updated.log_page_size == 123
    assert updated.run_history_limit == 456


def test_auth_store_verifies_password(tmp_path: Path):
    store = AuthStore(tmp_path / "auth.json")
    config = {
        "admin_username": "admin",
        "admin_password_hash": AuthStore.hash_password("demo123"),
        "session_secret": "secret",
    }
    store.save(config)
    assert store.verify("admin", "demo123") is True
    assert store.verify("admin", "bad") is False


def test_cleanup_old_logs_keeps_recent_files(tmp_path: Path):
    config_store = ConfigStore(tmp_path / "config.json")
    config_store.save(AppConfig(log_retention_days=3, run_retention_days=3))
    run_store = RunStore(tmp_path / "runs.json")
    service = JobService(config_store=config_store, run_store=run_store, data_dir=tmp_path)

    old_log = service.log_dir / "old.log"
    recent_log = service.log_dir / "recent.log"
    old_log.write_text("old", encoding="utf-8")
    recent_log.write_text("recent", encoding="utf-8")

    four_days_ago = 4 * 24 * 60 * 60
    old_mtime = old_log.stat().st_mtime - four_days_ago
    os.utime(old_log, (old_mtime, old_mtime))

    service.cleanup_old_logs()

    assert old_log.exists() is False
    assert recent_log.exists() is True


def test_cleanup_old_runs_keeps_recent_entries(tmp_path: Path):
    config_store = ConfigStore(tmp_path / "config.json")
    config_store.save(AppConfig(log_retention_days=3, run_retention_days=3, run_history_limit=200))
    run_store = RunStore(tmp_path / "runs.json")

    old_run = JobRun(
        run_id="old",
        job_type=JobType.CHECK,
        status=RunStatus.SUCCESS,
        trigger="manual",
        started_at=datetime.now(UTC) - timedelta(days=4),
        finished_at=datetime.now(UTC) - timedelta(days=4),
        duration_seconds=1.0,
        summary=JobSummary(),
        log_file=str(tmp_path / "logs" / "old.log"),
    )
    recent_run = JobRun(
        run_id="recent",
        job_type=JobType.CHECK,
        status=RunStatus.SUCCESS,
        trigger="manual",
        started_at=datetime.now(UTC) - timedelta(days=1),
        finished_at=datetime.now(UTC) - timedelta(days=1),
        duration_seconds=1.0,
        summary=JobSummary(),
        log_file=str(tmp_path / "logs" / "recent.log"),
    )
    run_store.save_runs([old_run, recent_run])

    service = JobService(config_store=config_store, run_store=run_store, data_dir=tmp_path)
    service.cleanup_old_runs()

    kept_ids = [run.run_id for run in run_store.list_runs()]
    assert kept_ids == ["recent"]
