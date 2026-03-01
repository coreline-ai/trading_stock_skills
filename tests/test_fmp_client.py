from __future__ import annotations

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
