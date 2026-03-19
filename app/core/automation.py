from __future__ import annotations

import logging
import sys
from collections import Counter
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests

from ..models import AppConfig, ChannelDecision, JobSummary

CODEX_CHANNEL_TYPE = 57
CODEX_WEEKLY_LIMIT_THRESHOLD = 100.0
CODEX_RESET_GRACE_SECONDS = 30
CODEX_SHORT_WINDOW_SECONDS = 18000

REASON_MESSAGES = {
    "suggest_reenable": "建议恢复",
    "weekly_window_blocked": "周窗口仍满，暂不恢复",
    "weekly_window_grace": "周窗口接近重置，建议恢复",
    "short_window_blocked": "短窗口仍受限，暂不恢复",
    "rate_limit_blocked": "限流窗口未重置，暂不恢复",
    "rate_limit_grace": "限流窗口接近重置，建议恢复",
    "not_allowed": "当前仍不允许请求，暂不恢复",
    "non_codex_review": "非 Codex 渠道，建议人工复核",
    "usage_error_401": "查询 usage 返回 401，已跳过",
    "usage_error_402": "查询 usage 返回 402，已跳过",
    "max_enable_per_run_reached": "达到单次最大恢复数量，已跳过",
    "deny_list": "命中禁止恢复名单，已跳过",
}


def setup_logger(log_path: Path, logger_name: str) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_codex_usage(usage: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    rate_limit = usage.get("rate_limit") or {}
    primary_window = rate_limit.get("primary_window") or {}
    secondary_window = rate_limit.get("secondary_window") or {}

    allowed = rate_limit.get("allowed")
    limit_reached = rate_limit.get("limit_reached")

    short_window_seconds = primary_window.get("limit_window_seconds")
    short_used_percent = to_float(primary_window.get("used_percent"))
    short_reset_after_seconds = to_float(primary_window.get("reset_after_seconds"))

    weekly_window_seconds = secondary_window.get("limit_window_seconds")
    weekly_used_percent = to_float(secondary_window.get("used_percent"))
    weekly_reset_after_seconds = to_float(secondary_window.get("reset_after_seconds"))

    suggestion = REASON_MESSAGES["suggest_reenable"]
    reason_code = "suggest_reenable"

    weekly_limit_hit = weekly_used_percent is not None and weekly_used_percent >= CODEX_WEEKLY_LIMIT_THRESHOLD
    short_window_detected = short_window_seconds == CODEX_SHORT_WINDOW_SECONDS
    short_limit_hit = (
        short_window_detected
        and limit_reached is True
        and allowed is False
        and short_reset_after_seconds is not None
        and short_reset_after_seconds > CODEX_RESET_GRACE_SECONDS
    )

    if weekly_limit_hit:
        if weekly_reset_after_seconds is None or weekly_reset_after_seconds > CODEX_RESET_GRACE_SECONDS:
            suggestion = REASON_MESSAGES["weekly_window_blocked"]
            reason_code = "weekly_window_blocked"
        else:
            suggestion = REASON_MESSAGES["weekly_window_grace"]
            reason_code = "weekly_window_grace"
    elif short_limit_hit:
        suggestion = REASON_MESSAGES["short_window_blocked"]
        reason_code = "short_window_blocked"
    elif limit_reached is True and allowed is False:
        if short_reset_after_seconds is not None and short_reset_after_seconds > CODEX_RESET_GRACE_SECONDS:
            suggestion = REASON_MESSAGES["rate_limit_blocked"]
            reason_code = "rate_limit_blocked"
        else:
            suggestion = REASON_MESSAGES["rate_limit_grace"]
            reason_code = "rate_limit_grace"
    elif allowed is False:
        suggestion = REASON_MESSAGES["not_allowed"]
        reason_code = "not_allowed"

    details = {
        "allowed": allowed,
        "limit_reached": limit_reached,
        "short_window_seconds": short_window_seconds,
        "short_used_percent": short_used_percent,
        "short_reset_after_seconds": short_reset_after_seconds,
        "weekly_window_seconds": weekly_window_seconds,
        "weekly_used_percent": weekly_used_percent,
        "weekly_reset_after_seconds": weekly_reset_after_seconds,
    }
    return suggestion, reason_code, details


class NewAPIClient:
    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.user_id: int | None = None

    def validate(self) -> None:
        missing = []
        if not self.config.new_api_base_url:
            missing.append("new_api_base_url")
        if not self.config.new_api_username:
            missing.append("new_api_username")
        if not self.config.new_api_password:
            missing.append("new_api_password")
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.config.new_api_base_url}{path}"
        response = self.session.request(method, url, timeout=self.config.request_timeout, **kwargs)
        response.raise_for_status()
        return response

    def login(self) -> None:
        payload = {"username": self.config.new_api_username, "password": self.config.new_api_password}
        response = self._request("POST", "/api/user/login", json=payload)
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(f"login failed: {data.get('message', 'unknown error')}")
        user = data.get("data") or {}
        self.user_id = user.get("id")
        if not self.user_id:
            raise RuntimeError("login succeeded but user id missing")
        self.session.headers.update({"New-Api-User": str(self.user_id)})
        self.logger.info("login success: user_id=%s username=%s", self.user_id, self.config.new_api_username)

    def get_channels(self) -> list[dict[str, Any]]:
        response = self._request(
            "GET",
            "/api/channel/",
            params={"p": 0, "page_size": 1000, "id_sort": "false", "tag_mode": "false"},
        )
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(f"list channels failed: {data.get('message', 'unknown error')}")
        payload = data.get("data")
        if isinstance(payload, dict):
            return payload.get("items") or payload.get("list") or payload.get("data") or []
        if isinstance(payload, list):
            return payload
        return []

    def get_channel_detail(self, channel_id: int) -> dict[str, Any]:
        response = self._request("GET", f"/api/channel/{channel_id}")
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(f"get channel {channel_id} failed: {data.get('message', 'unknown error')}")
        detail = data.get("data")
        if not isinstance(detail, dict):
            raise RuntimeError(f"channel {channel_id} detail payload invalid")
        return detail

    def get_codex_usage(self, channel_id: int) -> dict[str, Any]:
        response = self._request("GET", f"/api/channel/{channel_id}/codex/usage")
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(f"get codex usage {channel_id} failed: {data.get('message', 'unknown error')}")
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError(f"codex usage {channel_id} payload invalid")
        return payload

    def update_channel(self, channel_obj: dict[str, Any]) -> None:
        response = self._request("PUT", "/api/channel/", json=channel_obj)
        data = response.json()
        if not data.get("success"):
            raise RuntimeError(f"update channel {channel_obj.get('id')} failed: {data.get('message', 'unknown error')}")


class AutomationRunner:
    def __init__(self, config: AppConfig, log_path: Path):
        self.config = config
        self.log_path = log_path
        self.logger = setup_logger(log_path, f"job.{log_path.stem}")
        self.client = NewAPIClient(config, self.logger)

    def validate_connection(self) -> None:
        self.client.validate()
        self.client.login()

    def run_check(self) -> tuple[JobSummary, list[ChannelDecision]]:
        self.client.validate()
        self.client.login()
        channels = self.client.get_channels()
        auto_disabled = [channel for channel in channels if int(channel.get("status", 0)) == 3]

        summary = JobSummary(total=len(auto_disabled))
        decisions: list[ChannelDecision] = []
        self.logger.info("found auto-disabled channels=%s", len(auto_disabled))

        for channel in auto_disabled:
            channel_id = int(channel.get("id", 0))
            channel_name = channel.get("name", "")
            channel_type = int(channel.get("type", 0))
            if channel_type == CODEX_CHANNEL_TYPE:
                summary.codex += 1
                try:
                    usage = self.client.get_codex_usage(channel_id)
                    suggestion, reason_code, details = classify_codex_usage(usage)
                    setattr(summary, reason_code, getattr(summary, reason_code) + 1)
                    decisions.append(
                        ChannelDecision(
                            channel_id=channel_id,
                            channel_name=channel_name,
                            channel_type=channel_type,
                            action="check",
                            reason_code=reason_code,
                            suggestion=suggestion,
                            details=details,
                        )
                    )
                    self.logger.info(
                        "auto-disabled codex channel id=%s name=%s reason=%s suggestion=%s",
                        channel_id,
                        channel_name,
                        reason_code,
                        suggestion,
                    )
                except Exception as exc:
                    error_text = str(exc)
                    summary.usage_error += 1
                    reason_code = "usage_error_other"
                    if "401" in error_text:
                        summary.usage_error_401 += 1
                        reason_code = "usage_error_401"
                    elif "402" in error_text:
                        summary.usage_error_402 += 1
                        reason_code = "usage_error_402"
                    else:
                        summary.usage_error_other += 1
                    decisions.append(
                        ChannelDecision(
                            channel_id=channel_id,
                            channel_name=channel_name,
                            channel_type=channel_type,
                            action="check",
                            reason_code=reason_code,
                            suggestion=str(exc),
                        )
                    )
                    self.logger.error("usage_check_error channel_id=%s name=%s error=%s", channel_id, channel_name, exc)
            else:
                summary.non_codex += 1
                summary.non_codex_review += 1
                decisions.append(
                    ChannelDecision(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        action="check",
                        reason_code="non_codex_review",
                        suggestion=REASON_MESSAGES["non_codex_review"],
                    )
                )
                self.logger.info("auto-disabled non-codex channel id=%s name=%s", channel_id, channel_name)

        self.logger.info("summary=%s", summary.model_dump())
        return summary, decisions

    def _decision_from_usage(self, channel: dict[str, Any]) -> tuple[bool, ChannelDecision]:
        channel_id = int(channel.get("id", 0))
        channel_name = channel.get("name", "")
        usage = self.client.get_codex_usage(channel_id)
        suggestion, reason_code, details = classify_codex_usage(usage)
        return (
            reason_code in {"weekly_window_blocked", "short_window_blocked", "rate_limit_blocked", "not_allowed"},
            ChannelDecision(
                channel_id=channel_id,
                channel_name=channel_name,
                channel_type=int(channel.get("type", 0)),
                action="enable",
                reason_code=reason_code,
                suggestion=suggestion,
                details=details,
            ),
        )

    def run_enable(self) -> tuple[JobSummary, list[ChannelDecision]]:
        self.client.validate()
        self.client.login()
        channels = self.client.get_channels()
        auto_disabled = [channel for channel in channels if int(channel.get("status", 0)) == 3]

        summary = JobSummary(total=len(auto_disabled), dry_run=self.config.dry_run)
        decisions: list[ChannelDecision] = []
        success_count = 0

        self.logger.info("found auto-disabled channels=%s", len(auto_disabled))

        for channel in auto_disabled:
            channel_id = int(channel.get("id", 0))
            channel_name = channel.get("name", "")
            channel_type = int(channel.get("type", 0))

            if not channel_id:
                summary.skipped += 1
                decisions.append(ChannelDecision(channel_id=0, channel_name="", action="enable", reason_code="invalid_channel"))
                continue

            if channel_id in self.config.deny_channel_ids:
                summary.skipped += 1
                decisions.append(
                    ChannelDecision(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        action="enable",
                        reason_code="deny_list",
                        suggestion=REASON_MESSAGES["deny_list"],
                    )
                )
                continue

            if success_count >= self.config.max_enable_per_run:
                summary.skipped += 1
                summary.skipped_max_enable += 1
                decisions.append(
                    ChannelDecision(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        action="enable",
                        reason_code="max_enable_per_run_reached",
                        suggestion=REASON_MESSAGES["max_enable_per_run_reached"],
                    )
                )
                continue

            try:
                usage_decision: ChannelDecision | None = None
                if channel_type == CODEX_CHANNEL_TYPE:
                    should_skip, usage_decision = self._decision_from_usage(channel)
                    if should_skip:
                        summary.skipped += 1
                        if usage_decision.reason_code == "weekly_window_blocked":
                            summary.skipped_weekly_window_blocked += 1
                        elif usage_decision.reason_code == "short_window_blocked":
                            summary.skipped_short_window_blocked += 1
                        elif usage_decision.reason_code == "rate_limit_blocked":
                            summary.skipped_rate_limit_blocked += 1
                        elif usage_decision.reason_code == "not_allowed":
                            summary.skipped_not_allowed += 1
                        decisions.append(usage_decision)
                        continue

                detail = self.client.get_channel_detail(channel_id)
                detail["status"] = 1
                detail["priority"] = 0
                if self.config.dry_run:
                    summary.skipped += 1
                    summary.dry_run_skipped += 1
                    decisions.append(
                        ChannelDecision(
                            channel_id=channel_id,
                            channel_name=channel_name,
                            channel_type=channel_type,
                            action="enable",
                            reason_code="dry_run",
                            suggestion="Dry run 模式，未实际恢复",
                            details=(usage_decision.details if usage_decision else {}),
                        )
                    )
                    continue

                self.client.update_channel(detail)
                success_count += 1
                summary.success += 1
                reason_code = usage_decision.reason_code if usage_decision else "manual_review"
                decisions.append(
                    ChannelDecision(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        action="enable",
                        reason_code=reason_code,
                        suggestion="已恢复",
                        details=(usage_decision.details if usage_decision else {}),
                    )
                )
                self.logger.info("enabled channel id=%s name=%s", channel_id, channel_name)
            except Exception as exc:
                error_text = str(exc)
                if "401" in error_text:
                    summary.skipped += 1
                    summary.skipped_usage_401 += 1
                    reason_code = "usage_error_401"
                elif "402" in error_text:
                    summary.skipped += 1
                    summary.skipped_usage_402 += 1
                    reason_code = "usage_error_402"
                else:
                    summary.failed += 1
                    reason_code = "failed"
                decisions.append(
                    ChannelDecision(
                        channel_id=channel_id,
                        channel_name=channel_name,
                        channel_type=channel_type,
                        action="enable",
                        reason_code=reason_code,
                        suggestion=str(exc),
                    )
                )
                self.logger.error("enable error channel_id=%s name=%s error=%s", channel_id, channel_name, exc)

        self.logger.info("summary=%s", summary.model_dump())
        return summary, decisions
