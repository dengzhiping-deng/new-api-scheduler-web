from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobType(str, Enum):
    CHECK = "check"
    ENABLE = "enable"
    CHECK_AND_ENABLE = "check_and_enable"


class RunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    RUNNING = "running"


class AppConfig(BaseModel):
    new_api_base_url: str = "https://niu.chomoo.cc"
    new_api_username: str = ""
    new_api_password: str = ""
    request_timeout: int = 15
    max_enable_per_run: int = 10
    dry_run: bool = True
    deny_channel_ids: list[int] = Field(default_factory=list)
    schedule_enabled: bool = True
    auto_reenable_enabled: bool = True
    schedule_interval_minutes: int = 10
    log_page_size: int = 200
    log_retention_days: int = 3
    run_retention_days: int = 3
    run_history_limit: int = 200
    lock_ttl_minutes: int = 30

    @field_validator("new_api_base_url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator(
        "request_timeout",
        "max_enable_per_run",
        "schedule_interval_minutes",
        "log_page_size",
        "log_retention_days",
        "run_retention_days",
        "run_history_limit",
        "lock_ttl_minutes",
    )
    @classmethod
    def positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than 0")
        return value


class ConfigResponse(BaseModel):
    request_timeout: int
    max_enable_per_run: int
    dry_run: bool
    deny_channel_ids: list[int]
    schedule_enabled: bool
    auto_reenable_enabled: bool
    schedule_interval_minutes: int
    log_page_size: int
    log_retention_days: int
    run_retention_days: int
    run_history_limit: int
    lock_ttl_minutes: int


class ConfigUpdate(BaseModel):
    request_timeout: int
    max_enable_per_run: int
    dry_run: bool
    deny_channel_ids: list[int] = Field(default_factory=list)
    schedule_enabled: bool
    auto_reenable_enabled: bool
    schedule_interval_minutes: int
    log_page_size: int | None = None
    log_retention_days: int
    run_retention_days: int
    run_history_limit: int | None = None
    lock_ttl_minutes: int


class ValidationResult(BaseModel):
    ok: bool
    message: str


class SchedulerStatus(BaseModel):
    started: bool
    schedule_enabled: bool
    interval_minutes: int | None
    auto_reenable_enabled: bool
    next_run_time: datetime | None
    currently_running: bool


class ChannelDecision(BaseModel):
    channel_id: int
    channel_name: str
    channel_type: int | None = None
    action: str
    reason_code: str
    suggestion: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class JobSummary(BaseModel):
    total: int = 0
    codex: int = 0
    non_codex: int = 0
    suggest_reenable: int = 0
    weekly_window_blocked: int = 0
    weekly_window_grace: int = 0
    short_window_blocked: int = 0
    rate_limit_blocked: int = 0
    rate_limit_grace: int = 0
    not_allowed: int = 0
    non_codex_review: int = 0
    usage_error: int = 0
    usage_error_401: int = 0
    usage_error_402: int = 0
    usage_error_other: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    skipped_weekly_window_blocked: int = 0
    skipped_short_window_blocked: int = 0
    skipped_rate_limit_blocked: int = 0
    skipped_not_allowed: int = 0
    skipped_usage_401: int = 0
    skipped_usage_402: int = 0
    skipped_max_enable: int = 0
    dry_run_skipped: int = 0
    dry_run: bool = False


class JobRun(BaseModel):
    run_id: str
    job_type: JobType
    status: RunStatus
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    summary: JobSummary = Field(default_factory=JobSummary)
    decisions: list[ChannelDecision] = Field(default_factory=list)
    log_file: str
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    ok: bool
    scheduler: SchedulerStatus
    latest_run: JobRun | None = None


class LogResponse(BaseModel):
    path: str
    lines: list[str]


class TriggerResponse(BaseModel):
    run_id: str
    status: RunStatus
    started_at: datetime


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    ok: bool
    message: str
