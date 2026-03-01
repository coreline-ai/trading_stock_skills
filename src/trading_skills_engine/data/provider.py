from __future__ import annotations

import logging
import os
from datetime import date

from trading_skills_engine.core.models import MarketState, SymbolSignal
from trading_skills_engine.data.fmp_client import FMPClient
from trading_skills_engine.data.us_universe_store import USUniverseLoadError, USUniverseStore

logger = logging.getLogger(__name__)


class MarketDataUnavailableError(RuntimeError):
    pass


class MarketDataProvider:
    def __init__(self) -> None:
        self.client = FMPClient.from_env()
        self.universe_store = USUniverseStore(client=self.client)
        self._last_universe_meta = {
            "scope": "US",
            "source": "unavailable",
            "source_provider": "",
            "universe_mode": str(os.getenv("US_UNIVERSE_MODE") or "SP500_PLUS_NASDAQ_TOP500"),
            "ranking_basis": "",
            "raw_count": 0,
            "filtered_count": 0,
            "selected_count": 0,
            "sp500_count": 0,
            "nasdaq_top500_count": 0,
            "fetched_at": "",
        }

    def load_market_state(self) -> MarketState:
        state, _ = self.load_market_state_with_source()
        return state

    def load_market_state_with_source(self) -> tuple[MarketState, str]:
        self.universe_store.client = self.client
        try:
            snapshot = self.universe_store.load_symbols()
        except USUniverseLoadError as exc:
            self._last_universe_meta = self.universe_store.read_cached_meta()
            raise MarketDataUnavailableError(str(exc)) from exc

        symbols = snapshot.symbols
        self._last_universe_meta = dict(snapshot.meta)

        if not symbols:
            raise MarketDataUnavailableError("UNIVERSE_LOAD_FAILED:EMPTY_SYMBOLS")

        index = self._load_index_snapshot()
        breadth_up_ratio = self._breadth_up_ratio(symbols)
        recession_risk = self._recession_risk(
            spy_return_1d=index["spy_return_1d"],
            qqq_return_1d=index["qqq_return_1d"],
            tlt_return_1d=index["tlt_return_1d"],
            vix_level=index["vix_level"],
            breadth_up_ratio=breadth_up_ratio,
        )

        live_state = MarketState(
            as_of_date=date.today(),
            spy_return_1d=index["spy_return_1d"],
            qqq_return_1d=index["qqq_return_1d"],
            iwm_return_1d=index["iwm_return_1d"],
            tlt_return_1d=index["tlt_return_1d"],
            vix_level=index["vix_level"],
            breadth_up_ratio=breadth_up_ratio,
            recession_risk=recession_risk,
            symbols=symbols,
        )
        source = "fmp_live" if snapshot.meta.get("source") == "live" else "fmp_stale"
        return live_state, source

    def get_universe_meta(self) -> dict[str, object]:
        return dict(self._last_universe_meta)

    def _load_index_snapshot(self) -> dict[str, float]:
        defaults = {
            "spy_return_1d": 0.0,
            "qqq_return_1d": 0.0,
            "iwm_return_1d": 0.0,
            "tlt_return_1d": 0.0,
            "vix_level": 20.0,
        }
        if self.client is None:
            return defaults

        try:
            quotes = self.client.fetch_quotes(["SPY", "QQQ", "IWM", "TLT", "^VIX", "VIXY"])
        except Exception:
            logger.warning("fmp index quotes fetch failed. using index defaults", exc_info=True)
            return defaults

        quote_map = {
            str(item.get("symbol") or "").upper(): item
            for item in quotes
            if isinstance(item, dict)
        }
        result = dict(defaults)
        result["spy_return_1d"] = _change_pct(quote_map.get("SPY"), defaults["spy_return_1d"])
        result["qqq_return_1d"] = _change_pct(quote_map.get("QQQ"), defaults["qqq_return_1d"])
        result["iwm_return_1d"] = _change_pct(quote_map.get("IWM"), defaults["iwm_return_1d"])
        result["tlt_return_1d"] = _change_pct(quote_map.get("TLT"), defaults["tlt_return_1d"])
        result["vix_level"] = _vix_level(quote_map, defaults["vix_level"])
        return result

    @staticmethod
    def _breadth_up_ratio(symbols: list[SymbolSignal]) -> float:
        if not symbols:
            return 0.5
        up_count = sum(1 for item in symbols if item.daily_return_pct > 0)
        ratio = up_count / max(1, len(symbols))
        return max(0.0, min(1.0, round(ratio, 4)))

    @staticmethod
    def _recession_risk(
        spy_return_1d: float,
        qqq_return_1d: float,
        tlt_return_1d: float,
        vix_level: float,
        breadth_up_ratio: float,
    ) -> float:
        risk = 0.22
        if spy_return_1d < 0 and qqq_return_1d < 0:
            risk += 0.10
        risk += max(0.0, min(0.25, (vix_level - 18.0) / 40.0))
        risk += max(0.0, min(0.20, (tlt_return_1d - spy_return_1d) / 10.0))
        risk -= max(0.0, min(0.15, breadth_up_ratio - 0.55))
        return max(0.05, min(0.95, round(risk, 4)))


def _change_pct(row: dict | None, fallback: float) -> float:
    raw = None
    if isinstance(row, dict):
        raw = row.get("changePercentage")
        if raw is None:
            raw = row.get("changesPercentage")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


def _to_float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _vix_level(quote_map: dict[str, dict], fallback: float) -> float:
    if "^VIX" in quote_map:
        return _to_float(quote_map["^VIX"].get("price"), fallback)
    if "VIXY" in quote_map:
        # VIXY is an ETF proxy. We keep default unless quote is clearly meaningful.
        return max(fallback, _to_float(quote_map["VIXY"].get("price"), fallback))
    return fallback
