from __future__ import annotations

import json

import pytest

from trading_skills_engine.data.yahoo_finance_client import YahooFinanceClient, YahooFinanceError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_yahoo_fetch_quote_parses_metrics(monkeypatch):
    payload = {
        "quoteResponse": {
            "result": [
                {
                    "symbol": "NVDA",
                    "regularMarketPrice": 980.0,
                    "regularMarketChangePercent": 1.2,
                    "regularMarketVolume": 123456789,
                    "marketCap": 2500000000000,
                    "trailingPE": 75.3,
                    "currency": "USD",
                }
            ]
        }
    }
    monkeypatch.setattr(
        "trading_skills_engine.data.yahoo_finance_client.urlopen",
        lambda req, timeout=10: _FakeResponse(payload),  # noqa: ARG005
    )
    client = YahooFinanceClient()
    result = client.fetch_quote("NVDA")
    assert result["source"] == "yahoo"
    assert result["metrics"]["price"] == 980.0
    assert result["metrics"]["trailing_pe"] == 75.3


def test_yahoo_fetch_quote_raises_when_symbol_not_found(monkeypatch):
    payload = {"quoteResponse": {"result": []}}
    monkeypatch.setattr(
        "trading_skills_engine.data.yahoo_finance_client.urlopen",
        lambda req, timeout=10: _FakeResponse(payload),  # noqa: ARG005
    )
    client = YahooFinanceClient()
    with pytest.raises(YahooFinanceError):
        client.fetch_quote("MISSING")

