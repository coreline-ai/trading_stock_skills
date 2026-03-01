from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_skills_engine.data.us_universe_store import USUniverseLoadError, USUniverseStore


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def fetch_us_stock_list(self):
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


def test_us_universe_store_filters_and_caps_symbols(tmp_path: Path):
    rows = [
        {
            "symbol": "AAPL",
            "name": "Apple",
            "sector": "Technology",
            "exchangeShortName": "NASDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 2_500_000_000_000,
            "volume": 50_000_000,
            "price": 220.0,
            "changesPercentage": 1.2,
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "sector": "Technology",
            "exchangeShortName": "NASDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 2_300_000_000_000,
            "volume": 40_000_000,
            "price": 410.0,
            "changesPercentage": 0.9,
        },
        {
            "symbol": "SPY",
            "name": "SPDR S&P 500 ETF Trust",
            "exchangeShortName": "NYSEARCA",
            "type": "ETF",
            "isEtf": True,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 500_000_000_000,
            "volume": 100_000_000,
            "price": 500.0,
            "changesPercentage": 0.3,
        },
        {
            "symbol": "ZZZZ",
            "name": "Inactive Stock",
            "exchangeShortName": "NYSE",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": False,
            "marketCap": 5_000_000_000,
            "volume": 2_000_000,
            "price": 20.0,
            "changesPercentage": 0.2,
        },
    ]
    cache_path = tmp_path / "us_universe.json"
    store = USUniverseStore(
        client=_FakeClient(rows),
        cache_path=cache_path,
        ttl_min=60,
        max_symbols=1,
        min_market_cap=1_000_000_000,
        min_volume=500_000,
        allow_public_fallback=False,
        universe_mode="US_TOP_LIQUIDITY",
    )

    snapshot = store.load_symbols()
    assert snapshot.meta["source"] == "live"
    assert snapshot.meta["raw_count"] == 4
    assert snapshot.meta["filtered_count"] == 2
    assert snapshot.meta["selected_count"] == 1
    assert len(snapshot.symbols) == 1
    assert snapshot.symbols[0].symbol in {"AAPL", "MSFT"}


def test_us_universe_store_falls_back_to_stale_cache(tmp_path: Path):
    cache_path = tmp_path / "us_universe.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "scope": "US",
                "source": "live",
                "raw_count": 2,
                "filtered_count": 2,
                "selected_count": 2,
                "fetched_at": "2026-02-28T00:00:00+00:00",
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple",
                        "sector": "Technology",
                        "daily_return_pct": 1.2,
                        "momentum_20d": 3.1,
                        "ai_factor": 0.8,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = USUniverseStore(
        client=_FakeClient(RuntimeError("network down")),
        cache_path=cache_path,
        ttl_min=1,
        max_symbols=2000,
        min_market_cap=1.0,
        min_volume=1.0,
        allow_public_fallback=False,
        universe_mode="US_TOP_LIQUIDITY",
    )

    snapshot = store.load_symbols()
    assert snapshot.meta["source"] == "stale"
    assert snapshot.symbols[0].symbol == "AAPL"


def test_us_universe_store_raises_on_cold_start_without_client(tmp_path: Path):
    store = USUniverseStore(
        client=None,
        cache_path=tmp_path / "missing.json",
        ttl_min=60,
        max_symbols=2000,
        min_market_cap=1.0,
        min_volume=1.0,
        allow_public_fallback=False,
        universe_mode="US_TOP_LIQUIDITY",
    )
    with pytest.raises(USUniverseLoadError):
        store.load_symbols()


def test_us_universe_store_sp500_plus_nasdaq_top500_mode(tmp_path: Path):
    rows = [
        {
            "symbol": "AAPL",
            "name": "Apple",
            "sector": "Technology",
            "exchangeShortName": "NASDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 3_000_000_000_000,
            "volume": 50_000_000,
            "price": 220.0,
            "changesPercentage": 1.2,
        },
        {
            "symbol": "MSFT",
            "name": "Microsoft",
            "sector": "Technology",
            "exchangeShortName": "NASDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 2_900_000_000_000,
            "volume": 40_000_000,
            "price": 410.0,
            "changesPercentage": 0.9,
        },
        {
            "symbol": "XOM",
            "name": "Exxon",
            "sector": "Energy",
            "exchangeShortName": "NYSE",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 500_000_000_000,
            "volume": 10_000_000,
            "price": 100.0,
            "changesPercentage": 0.5,
        },
        {
            "symbol": "QQQX",
            "name": "Nasdaq Midcap",
            "sector": "Technology",
            "exchangeShortName": "NASDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 5_000_000_000,
            "volume": 1_000_000,
            "price": 20.0,
            "changesPercentage": 0.1,
        },
    ]
    cache_path = tmp_path / "us_universe.json"
    store = USUniverseStore(
        client=_FakeClient(rows),
        cache_path=cache_path,
        ttl_min=60,
        max_symbols=2000,
        min_market_cap=1.0,
        min_volume=1.0,
        allow_public_fallback=False,
        universe_mode="SP500_PLUS_NASDAQ_TOP500",
    )
    store._fetch_sp500_symbols = lambda: {"AAPL", "XOM"}  # type: ignore[method-assign]

    snapshot = store.load_symbols()
    symbols = {item.symbol for item in snapshot.symbols}
    assert {"AAPL", "XOM", "MSFT", "QQQX"}.issubset(symbols)
    assert snapshot.meta["universe_mode"] == "SP500_PLUS_NASDAQ_TOP500"
    assert snapshot.meta["sp500_count"] >= 2
    assert snapshot.meta["nasdaq_top500_count"] >= 3
