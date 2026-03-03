from __future__ import annotations

import json
import time
from urllib.error import HTTPError

import pytest

from trading_skills_engine.data.fmp_client import FMPClient


def test_fetch_us_stock_list_returns_dict_rows(monkeypatch):
    client = FMPClient(api_key="test-key", usage_tracker=None)

    def _fake_get(self, path, params=None):
        del self
        del params
        assert path == "/stock-list"
        return [{"symbol": "AAPL"}, {"symbol": "MSFT"}, "x", 1]

    monkeypatch.setattr(FMPClient, "_get", _fake_get)
    rows = client.fetch_us_stock_list()
    assert rows == [{"symbol": "AAPL"}, {"symbol": "MSFT"}]


def test_fetch_us_stock_list_raises_on_invalid_payload(monkeypatch):
    client = FMPClient(api_key="test-key", usage_tracker=None)

    def _fake_get(self, path, params=None):
        del self, path, params
        return {"symbol": "AAPL"}

    monkeypatch.setattr(FMPClient, "_get", _fake_get)
    with pytest.raises(RuntimeError):
        client.fetch_us_stock_list()


def test_fmp_client_sets_cooldown_on_http_429(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime" / "fmp_rate_limit_state.json"
    monkeypatch.setenv("FMP_RATE_LIMIT_STATE_PATH", str(state_path))
    monkeypatch.setenv("FMP_HTTP_RETRY_DELAYS_SEC", "1,2")
    monkeypatch.setenv("FMP_RATE_LIMIT_COOLDOWN_SEC", "120")
    client = FMPClient(api_key="test-key", usage_tracker=None)

    sleep_calls: list[float] = []
    attempts = {"count": 0}

    def _fake_sleep(seconds: float):
        sleep_calls.append(float(seconds))

    def _fake_urlopen(_req, timeout=8):
        del timeout
        attempts["count"] += 1
        raise HTTPError(url="https://example.com", code=429, msg="Too Many Requests", hdrs=None, fp=None)

    monkeypatch.setattr("trading_skills_engine.data.fmp_client.time.sleep", _fake_sleep)
    monkeypatch.setattr("trading_skills_engine.data.fmp_client.urlopen", _fake_urlopen)

    with pytest.raises(RuntimeError, match="FMP_HTTP_429"):
        client._get("/quote", {"symbol": "AAPL"})

    assert attempts["count"] == 3
    assert sleep_calls == [1.0, 2.0]
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["blocked_until_epoch"] > payload["last_429_epoch"] >= time.time() - 10


def test_fmp_client_skips_network_when_cooldown_active(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime" / "fmp_rate_limit_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"last_429_epoch": time.time(), "blocked_until_epoch": time.time() + 60}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FMP_RATE_LIMIT_STATE_PATH", str(state_path))
    client = FMPClient(api_key="test-key", usage_tracker=None)

    called = {"count": 0}

    def _fake_urlopen(_req, timeout=8):
        del timeout
        called["count"] += 1
        raise AssertionError("network should not be called during cooldown")

    monkeypatch.setattr("trading_skills_engine.data.fmp_client.urlopen", _fake_urlopen)

    with pytest.raises(RuntimeError, match="FMP_RATE_LIMIT_COOLDOWN"):
        client._get("/quote", {"symbol": "AAPL"})

    assert called["count"] == 0
