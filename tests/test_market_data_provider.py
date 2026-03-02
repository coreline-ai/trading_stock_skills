from __future__ import annotations

import json
from pathlib import Path

import pytest

from trading_skills_engine.core.models import SymbolSignal
from trading_skills_engine.data.kr_universe_store import KRUniverseStore
from trading_skills_engine.data.provider import MarketDataProvider
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


def test_us_universe_store_uses_real_backup_provider_when_fmp_fails(tmp_path: Path):
    cache_path = tmp_path / "us_universe.json"
    store = USUniverseStore(
        client=_FakeClient(RuntimeError("fmp down")),
        cache_path=cache_path,
        ttl_min=60,
        max_symbols=2000,
        min_market_cap=1.0,
        min_volume=1.0,
        allow_public_fallback=True,
        universe_mode="US_TOP_LIQUIDITY",
    )

    store._load_nasdaq_screener_universe = lambda: (  # type: ignore[method-assign]
        [
            SymbolSignal(
                symbol="AAPL",
                name="Apple Inc",
                sector="Technology",
                daily_return_pct=1.2,
                momentum_20d=3.4,
                ai_factor=0.91,
            )
        ],
        1,
        1,
        {"sp500_count": 1, "nasdaq_top500_count": 1, "filtered_count": 1},
    )

    snapshot = store.load_symbols()
    assert snapshot.meta["source"] == "live"
    assert snapshot.meta["source_provider"] == "nasdaq_screener"
    assert snapshot.meta["selected_count"] == 1
    assert snapshot.symbols[0].symbol == "AAPL"


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


def test_kr_universe_store_kospi500_kosdaq200_mode(tmp_path: Path):
    rows = [
        {
            "symbol": "005930.KS",
            "name": "Samsung Electronics Co Ltd",
            "sector": "Technology",
            "exchangeShortName": "KOSPI",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 300_000_000_000,
            "volume": 1_500_000,
            "price": 71_200.0,
            "changesPercentage": 1.1,
        },
        {
            "symbol": "000660.KS",
            "name": "SK hynix Inc",
            "sector": "Technology",
            "exchangeShortName": "KOSPI",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 120_000_000_000,
            "volume": 900_000,
            "price": 122_000.0,
            "changesPercentage": 0.6,
        },
        {
            "symbol": "035420.KQ",
            "name": "NAVER Corp",
            "sector": "Technology",
            "exchangeShortName": "KOSDAQ",
            "type": "Common Stock",
            "isEtf": False,
            "isFund": False,
            "isActivelyTrading": True,
            "marketCap": 40_000_000_000,
            "volume": 600_000,
            "price": 172_000.0,
            "changesPercentage": 0.4,
        },
    ]
    cache_path = tmp_path / "kr_universe.json"
    store = KRUniverseStore(
        client=_FakeClient(rows),
        cache_path=cache_path,
        ttl_min=60,
        max_symbols=700,
        min_market_cap=1.0,
        min_volume=1.0,
        universe_mode="KOSPI500_KOSDAQ200",
    )

    snapshot = store.load_symbols()
    symbols = {item.symbol for item in snapshot.symbols}
    assert snapshot.meta["scope"] == "KR"
    assert snapshot.meta["selected_count"] == 3
    assert "005930" in symbols
    assert "000660" in symbols
    assert "035420" in symbols


def test_market_data_provider_uses_runtime_scope_kr(tmp_path: Path, monkeypatch):
    scope_path = tmp_path / "runtime" / "market_scope.json"
    scope_path.parent.mkdir(parents=True, exist_ok=True)
    scope_path.write_text(json.dumps({"scope": "KR"}), encoding="utf-8")
    monkeypatch.setenv("MARKET_SCOPE_RUNTIME_SETTINGS_PATH", str(scope_path))
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")

    provider = MarketDataProvider()

    class _FakeStore:
        def __init__(self, scope: str):
            self.scope = scope
            self.client = None

        def load_symbols(self):
            return type(
                "Snapshot",
                (),
                {
                    "symbols": [
                        SymbolSignal(
                            symbol="005930",
                            name="Samsung Electronics",
                            sector="Technology",
                            daily_return_pct=0.8,
                            momentum_20d=3.2,
                            ai_factor=0.9,
                        )
                    ],
                    "meta": {
                        "scope": self.scope,
                        "source": "live",
                        "selected_count": 1,
                        "filtered_count": 1,
                        "raw_count": 1,
                        "universe_mode": "KOSPI500_KOSDAQ200",
                    },
                },
            )()

        def read_cached_meta(self):
            return {"scope": self.scope, "source": "stale"}

    provider.kr_universe_store = _FakeStore("KR")
    provider.us_universe_store = _FakeStore("US")
    provider._load_index_snapshot = lambda scope: {  # type: ignore[method-assign]
        "spy_return_1d": 0.0,
        "qqq_return_1d": 0.0,
        "iwm_return_1d": 0.0,
        "tlt_return_1d": 0.0,
        "vix_level": 20.0,
    }

    state, source = provider.load_market_state_with_source()
    assert source == "fmp_live"
    assert provider.get_market_scope() == "KR"
    assert provider.get_universe_meta()["scope"] == "KR"
    assert state.symbols[0].symbol == "005930"
