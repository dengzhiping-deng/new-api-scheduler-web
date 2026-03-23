from __future__ import annotations

import json
import hashlib
import hmac
import secrets
from pathlib import Path

from .models import AppConfig, ConfigResponse, ConfigUpdate


class ConfigStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        if not self.path.exists():
            config = self._load_legacy_or_default()
            self.save(config)
            return config
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(data)

    def save(self, config: AppConfig) -> AppConfig:
        self.path.write_text(
            json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return config

    def update(self, payload: ConfigUpdate) -> AppConfig:
        current = self.load()
        merged = AppConfig(
            new_api_base_url=current.new_api_base_url,
            new_api_username=current.new_api_username,
            new_api_password=current.new_api_password,
            log_page_size=current.log_page_size,
            run_history_limit=current.run_history_limit,
            **payload.model_dump(),
        )
        return self.save(merged)

    @staticmethod
    def to_response(config: AppConfig) -> ConfigResponse:
        return ConfigResponse(
            **config.model_dump(
                exclude={
                    "new_api_base_url",
                    "new_api_username",
                    "new_api_password",
                    "log_page_size",
                    "run_history_limit",
                }
            )
        )

    def _load_legacy_or_default(self) -> AppConfig:
        legacy_path = self.path.parent.parent.parent / "脚本中心" / "配置文件" / "new-api-auto-enable.env"
        if not legacy_path.exists():
            return AppConfig()

        raw: dict[str, str] = {}
        for line in legacy_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            raw[key.strip()] = value.strip()

        deny_ids = [int(item.strip()) for item in raw.get("DENY_CHANNEL_IDS", "").split(",") if item.strip()]
        return AppConfig(
            new_api_base_url=raw.get("NEW_API_BASE_URL", "https://niu.chomoo.cc"),
            new_api_username=raw.get("NEW_API_USERNAME", ""),
            new_api_password=raw.get("NEW_API_PASSWORD", ""),
            request_timeout=int(raw.get("REQUEST_TIMEOUT", 15)),
            max_enable_per_run=int(raw.get("MAX_ENABLE_PER_RUN", 10)),
            dry_run=raw.get("DRY_RUN", "true").lower() in {"1", "true", "yes", "on"},
            deny_channel_ids=deny_ids,
        )


class AuthStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            default = self._default_config()
            self.save(default)
            return default
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, str]) -> None:
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def verify(self, username: str, password: str) -> bool:
        config = self.load()
        if username != config["admin_username"]:
            return False
        expected = config["admin_password_hash"]
        actual = self.hash_password(password)
        return hmac.compare_digest(actual, expected)

    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    @staticmethod
    def _default_config() -> dict[str, str]:
        default_password = "admin123456"
        return {
            "admin_username": "admin",
            "admin_password_hash": AuthStore.hash_password(default_password),
            "session_secret": secrets.token_hex(32),
        }
