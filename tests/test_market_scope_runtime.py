from __future__ import annotations

import json
from pathlib import Path

from trading_skills_engine.config.market_scope_runtime import (
    MarketScopeRuntimeSettingsStore,
    normalize_market_scope,
)


def test_market_scope_runtime_store_reads_env_default(monkeypatch):
    monkeypatch.delenv("MARKET_SCOPE_RUNTIME_SETTINGS_PATH", raising=False)
    monkeypatch.setenv("MARKET_SCOPE", "kr")
    settings = MarketScopeRuntimeSettingsStore(settings_path=Path("/tmp/non-existent-market-scope.json")).read()
    assert settings.scope == "KR"


def test_market_scope_runtime_store_set_scope(tmp_path: Path, monkeypatch):
    settings_path = tmp_path / "runtime" / "market_scope.json"
    monkeypatch.setenv("MARKET_SCOPE_RUNTIME_SETTINGS_PATH", str(settings_path))

    store = MarketScopeRuntimeSettingsStore()
    store.set_scope("KR")
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    assert payload["scope"] == "KR"
    assert store.read().scope == "KR"


def test_market_scope_normalize_fallback():
    assert normalize_market_scope("US") == "US"
    assert normalize_market_scope("kr") == "KR"
    assert normalize_market_scope("invalid") == "US"

