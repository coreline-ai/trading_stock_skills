from __future__ import annotations

import pytest

from trading_skills_engine.data.stooq_client import StooqClient, StooqError


class _FakeResponse:
    def __init__(self, payload: str):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_stooq_fetch_quote_parses_headerless_csv(monkeypatch):
    raw = "AAPL.US,20260227,220020,272.81,272.81,262.89,264.18,72232024,\r\n"
    monkeypatch.setattr(
        "trading_skills_engine.data.stooq_client.urlopen",
        lambda req, timeout=10: _FakeResponse(raw),  # noqa: ARG005
    )
    client = StooqClient()
    result = client.fetch_quote("AAPL")
    assert result["source"] == "stooq"
    assert result["metrics"]["close"] == 264.18
    assert result["metrics"]["volume"] == 72232024.0


def test_stooq_fetch_quote_parses_header_csv(monkeypatch):
    raw = (
        "Symbol,Date,Time,Open,High,Low,Close,Volume\r\n"
        "NVDA.US,20260227,220020,178.10,179.20,176.20,177.19,307958795\r\n"
    )
    monkeypatch.setattr(
        "trading_skills_engine.data.stooq_client.urlopen",
        lambda req, timeout=10: _FakeResponse(raw),  # noqa: ARG005
    )
    client = StooqClient()
    result = client.fetch_quote("NVDA")
    assert result["metrics"]["close"] == 177.19


def test_stooq_fetch_quote_raises_when_symbol_not_found(monkeypatch):
    raw = "AAPL.US,20260227,220020,N/D,N/D,N/D,N/D,N/D,\r\n"
    monkeypatch.setattr(
        "trading_skills_engine.data.stooq_client.urlopen",
        lambda req, timeout=10: _FakeResponse(raw),  # noqa: ARG005
    )
    client = StooqClient()
    with pytest.raises(StooqError):
        client.fetch_quote("AAPL")
