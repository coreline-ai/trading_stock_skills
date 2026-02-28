from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


DEFAULT_FMP_DAILY_LIMIT = 250
DEFAULT_FMP_USAGE_PATH = Path("reports/runtime/fmp_usage.json")


@dataclass
class FMPUsageSnapshot:
    as_of_date: str
    used_today: int
    daily_limit: int


class FMPUsageTracker:
    def __init__(self, usage_path: Path | None = None, daily_limit: int = DEFAULT_FMP_DAILY_LIMIT) -> None:
        env_path = os.getenv("FMP_USAGE_PATH")
        self.usage_path = Path(env_path) if env_path else (usage_path or DEFAULT_FMP_USAGE_PATH)
        self.daily_limit = max(1, int(daily_limit))

    def snapshot(self) -> FMPUsageSnapshot:
        state = self._load_state(persist_reset=True)
        return FMPUsageSnapshot(
            as_of_date=state["date"],
            used_today=state["used_today"],
            daily_limit=self.daily_limit,
        )

    def try_consume(self) -> bool:
        state = self._load_state(persist_reset=True)
        if state["used_today"] >= self.daily_limit:
            return False
        state["used_today"] += 1
        self._write_state(state)
        return True

    def _load_state(self, persist_reset: bool) -> dict[str, Any]:
        today = date.today().isoformat()
        payload = self._read_json()
        raw_date = str(payload.get("date") or "")
        raw_used = payload.get("used_today")
        try:
            used_today = int(raw_used)
        except (TypeError, ValueError):
            used_today = 0

        if raw_date != today:
            state = {"date": today, "used_today": 0}
            if persist_reset:
                self._write_state(state)
            return state

        return {"date": today, "used_today": max(0, used_today)}

    def _read_json(self) -> dict[str, Any]:
        if not self.usage_path.exists():
            return {}
        try:
            raw = json.loads(self.usage_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_state(self, payload: dict[str, Any]) -> None:
        self.usage_path.parent.mkdir(parents=True, exist_ok=True)
        self.usage_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

