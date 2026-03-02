from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading_skills_engine.config.env import ensure_project_env_loaded

DEFAULT_MARKET_SCOPE_SETTINGS_PATH = Path("reports/runtime/market_scope.json")
DEFAULT_MARKET_SCOPE = "US"
ALLOWED_MARKET_SCOPES = {"US", "KR"}


def normalize_market_scope(raw: Any) -> str:
    scope = str(raw or "").strip().upper()
    if scope in ALLOWED_MARKET_SCOPES:
        return scope
    return DEFAULT_MARKET_SCOPE


@dataclass
class MarketScopeRuntimeSettings:
    scope: str


class MarketScopeRuntimeSettingsStore:
    def __init__(self, settings_path: Path | None = None) -> None:
        ensure_project_env_loaded()
        env_path = os.getenv("MARKET_SCOPE_RUNTIME_SETTINGS_PATH")
        self.settings_path = (
            Path(env_path)
            if env_path
            else (settings_path or DEFAULT_MARKET_SCOPE_SETTINGS_PATH)
        )

    def read(self) -> MarketScopeRuntimeSettings:
        payload = self._read_json()
        env_scope = normalize_market_scope(os.getenv("MARKET_SCOPE"))
        scope = normalize_market_scope(payload.get("scope")) if payload else env_scope
        return MarketScopeRuntimeSettings(scope=scope)

    def set_scope(self, scope: str) -> MarketScopeRuntimeSettings:
        normalized = normalize_market_scope(scope)
        next_settings = MarketScopeRuntimeSettings(scope=normalized)
        self._write_json({"scope": normalized})
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


def get_market_scope_runtime_state() -> dict[str, Any]:
    settings = MarketScopeRuntimeSettingsStore().read()
    return {
        "scope": settings.scope,
        "available_scopes": sorted(ALLOWED_MARKET_SCOPES),
    }

