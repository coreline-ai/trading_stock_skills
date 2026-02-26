from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from trading_skills_engine.core.models import MarketState, SymbolSignal
from trading_skills_engine.data.fmp_client import FMPClient

SAMPLE_STATE_PATH = Path(__file__).resolve().parent / "sample_market_state.json"


class MarketDataProvider:
    def __init__(self, sample_path: Path | None = None) -> None:
        self.sample_path = sample_path or SAMPLE_STATE_PATH
        self.client = FMPClient.from_env()

    def load_market_state(self) -> MarketState:
        state, _ = self.load_market_state_with_source()
        return state

    def load_market_state_with_source(self) -> tuple[MarketState, str]:
        sample_payload = json.loads(self.sample_path.read_text(encoding="utf-8"))
        state = self._state_from_payload(sample_payload)

        if not self.client:
            return state, "sample"

        try:
            quotes = self.client.fetch_quotes(["SPY", "QQQ", "IWM", "TLT", "AAPL", "MSFT", "NVDA", "AMZN"])
        except Exception:
            return state, "sample"

        if not quotes:
            return state, "sample"

        quote_map = {item.get("symbol"): item for item in quotes if isinstance(item, dict)}

        def _change(symbol: str, fallback: float) -> float:
            raw = quote_map.get(symbol, {}).get("changesPercentage")
            try:
                return float(raw)
            except (TypeError, ValueError):
                return fallback

        updated_symbols: list[SymbolSignal] = []
        for symbol in state.symbols:
            quote = quote_map.get(symbol.symbol, {})
            daily = quote.get("changesPercentage")
            price = quote.get("price")
            prev = quote.get("previousClose")
            try:
                daily_return = float(daily)
            except (TypeError, ValueError):
                daily_return = symbol.daily_return_pct

            try:
                momentum = ((float(price) - float(prev)) / float(prev)) * 100 if float(prev) > 0 else symbol.momentum_20d
            except (TypeError, ValueError, ZeroDivisionError):
                momentum = symbol.momentum_20d

            updated_symbols.append(
                SymbolSignal(
                    symbol=symbol.symbol,
                    name=symbol.name,
                    sector=symbol.sector,
                    daily_return_pct=daily_return,
                    momentum_20d=momentum,
                    ai_factor=symbol.ai_factor,
                )
            )

        live_state = MarketState(
            as_of_date=date.today(),
            spy_return_1d=_change("SPY", state.spy_return_1d),
            qqq_return_1d=_change("QQQ", state.qqq_return_1d),
            iwm_return_1d=_change("IWM", state.iwm_return_1d),
            tlt_return_1d=_change("TLT", state.tlt_return_1d),
            vix_level=state.vix_level,
            breadth_up_ratio=state.breadth_up_ratio,
            recession_risk=state.recession_risk,
            symbols=updated_symbols,
        )
        return live_state, "fmp_live"

    @staticmethod
    def _state_from_payload(payload: dict) -> MarketState:
        raw_symbols = payload.get("symbols") if isinstance(payload.get("symbols"), list) else []
        symbols = [
            SymbolSignal(
                symbol=str(item.get("symbol", "-")),
                name=str(item.get("name", "Unknown")),
                sector=str(item.get("sector", "Unknown")),
                daily_return_pct=float(item.get("daily_return_pct", 0.0)),
                momentum_20d=float(item.get("momentum_20d", 0.0)),
                ai_factor=float(item.get("ai_factor", 0.5)),
            )
            for item in raw_symbols
            if isinstance(item, dict)
        ]

        as_of_raw = str(payload.get("as_of_date", date.today().isoformat()))
        try:
            as_of_date = datetime.strptime(as_of_raw, "%Y-%m-%d").date()
        except ValueError:
            as_of_date = date.today()

        return MarketState(
            as_of_date=as_of_date,
            spy_return_1d=float(payload.get("spy_return_1d", 0.0)),
            qqq_return_1d=float(payload.get("qqq_return_1d", 0.0)),
            iwm_return_1d=float(payload.get("iwm_return_1d", 0.0)),
            tlt_return_1d=float(payload.get("tlt_return_1d", 0.0)),
            vix_level=float(payload.get("vix_level", 20.0)),
            breadth_up_ratio=float(payload.get("breadth_up_ratio", 0.5)),
            recession_risk=float(payload.get("recession_risk", 0.3)),
            symbols=symbols,
        )
