from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import JobRun


class RunStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_runs(self) -> list[JobRun]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [JobRun.model_validate(item) for item in payload]

    def save_runs(self, runs: list[JobRun]) -> None:
        self.path.write_text(
            json.dumps([run.model_dump(mode="json") for run in runs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def append(self, run: JobRun, limit: int) -> None:
        runs = self.list_runs()
        runs.insert(0, run)
        self.save_runs(runs[:limit])

    def replace(self, run: JobRun, limit: int) -> None:
        runs = self.list_runs()
        updated: list[JobRun] = []
        replaced = False
        for item in runs:
            if item.run_id == run.run_id:
                updated.append(run)
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.insert(0, run)
        self.save_runs(updated[:limit])

    def get(self, run_id: str) -> JobRun | None:
        for run in self.list_runs():
            if run.run_id == run_id:
                return run
        return None

    def cleanup_old_runs(self, retention_days: int, limit: int) -> list[JobRun]:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        kept = [run for run in self.list_runs() if run.started_at >= cutoff]
        kept.sort(key=lambda run: run.started_at, reverse=True)
        kept = kept[:limit]
        self.save_runs(kept)
        return kept
