from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_skills_engine.config.env import ensure_project_env_loaded
from trading_skills_engine.data.fmp_usage_tracker import (
    DEFAULT_FMP_DAILY_LIMIT,
    FMPUsageTracker,
)

DEFAULT_FMP_SETTINGS_PATH = Path("reports/runtime/fmp_settings.json")


@dataclass
class FMPRuntimeSettings:
    enabled: bool
    daily_limit: int


class FMPRuntimeSettingsStore:
    def __init__(self, settings_path: Path | None = None) -> None:
        ensure_project_env_loaded()
        env_path = os.getenv("FMP_RUNTIME_SETTINGS_PATH")
        self.settings_path = Path(env_path) if env_path else (settings_path or DEFAULT_FMP_SETTINGS_PATH)

    def read(self) -> FMPRuntimeSettings:
        payload = self._read_json()
        default_enabled = True
        enabled = payload.get("enabled")
        if isinstance(enabled, bool):
            toggle_enabled = enabled
        else:
            toggle_enabled = default_enabled

        raw_limit = payload.get("daily_limit", DEFAULT_FMP_DAILY_LIMIT)
        try:
            daily_limit = max(1, int(raw_limit))
        except (TypeError, ValueError):
            daily_limit = DEFAULT_FMP_DAILY_LIMIT

        return FMPRuntimeSettings(
            enabled=toggle_enabled,
            daily_limit=daily_limit,
        )

    def set_enabled(self, enabled: bool) -> FMPRuntimeSettings:
        current = self.read()
        next_settings = FMPRuntimeSettings(enabled=bool(enabled), daily_limit=current.daily_limit)
        self._write_json(
            {
                "enabled": next_settings.enabled,
                "daily_limit": next_settings.daily_limit,
            }
        )
        return next_settings

    def _read_json(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_json(self, payload: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def get_fmp_runtime_state() -> dict[str, Any]:
    ensure_project_env_loaded()
    settings = FMPRuntimeSettingsStore().read()
    usage = FMPUsageTracker(daily_limit=settings.daily_limit).snapshot()
    api_configured = bool(os.getenv("FMP_API_KEY"))
    effective_enabled = settings.enabled and api_configured
    return {
        "toggle_enabled": settings.enabled,
        "effective_enabled": effective_enabled,
        "api_configured": api_configured,
        "used_today": usage.used_today,
        "daily_limit": usage.daily_limit,
        "usage_label": f"{usage.used_today}/{usage.daily_limit}",
    }
