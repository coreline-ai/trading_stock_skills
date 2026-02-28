from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from trading_skills_engine.data.fmp_client import FMPClient
from trading_skills_engine.data.fmp_usage_tracker import FMPUsageTracker


def test_fmp_client_from_env_returns_none_when_toggle_is_off(tmp_path, monkeypatch):
    settings_path = tmp_path / "runtime" / "fmp_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"enabled": False, "daily_limit": 250}), encoding="utf-8")

    monkeypatch.setenv("FMP_RUNTIME_SETTINGS_PATH", str(settings_path))
    monkeypatch.setenv("FMP_API_KEY", "dummy")

    assert FMPClient.from_env() is None


def test_fmp_usage_tracker_respects_daily_limit(tmp_path, monkeypatch):
    usage_path = tmp_path / "runtime" / "fmp_usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps({"date": date.today().isoformat(), "used_today": 249}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FMP_USAGE_PATH", str(usage_path))

    tracker = FMPUsageTracker(daily_limit=250)
    assert tracker.try_consume() is True
    assert tracker.try_consume() is False

    payload = json.loads(usage_path.read_text(encoding="utf-8"))
    assert payload["used_today"] == 250


def test_fmp_client_reads_key_from_dotenv_file(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("FMP_API_KEY=dotenv-key\n", encoding="utf-8")

    settings_path = tmp_path / "runtime" / "fmp_settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({"enabled": True, "daily_limit": 250}), encoding="utf-8")

    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_ENV_FILE", str(env_path))
    monkeypatch.setenv("FMP_RUNTIME_SETTINGS_PATH", str(settings_path))

    client = FMPClient.from_env()
    assert client is not None
    assert client.api_key == "dotenv-key"
