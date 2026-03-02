from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trading_skills_engine.core.models import SymbolSignal
from trading_skills_engine.data.fmp_client import FMPClient

logger = logging.getLogger(__name__)

DEFAULT_KR_UNIVERSE_CACHE_PATH = Path("reports/cache/universe/kr_universe.json")
DEFAULT_KR_UNIVERSE_TTL_MIN = 60
DEFAULT_KR_UNIVERSE_MAX_SYMBOLS = 700
DEFAULT_KR_UNIVERSE_MIN_MARKET_CAP = 100_000_000.0
DEFAULT_KR_UNIVERSE_MIN_VOLUME = 10_000.0
DEFAULT_KR_UNIVERSE_MODE = "KOSPI500_KOSDAQ200"
KR_UNIVERSE_MODE_INDEX_BLEND = "KOSPI500_KOSDAQ200"
KR_UNIVERSE_MODE_LIQUIDITY = "KR_TOP_LIQUIDITY"

SYMBOL_RE = re.compile(r"[0-9]{6}|[0-9]{6}\.[A-Z]{2,4}")
EXCLUDED_TYPE_KEYWORDS = (
    "etf",
    "fund",
    "adr",
    "warrant",
    "right",
    "unit",
    "preferred",
    "bond",
    "note",
    "trust",
    "index",
    "reit",
)
EXCLUDED_NAME_KEYWORDS = (
    " etf",
    " etn",
    " preferred",
    " 우선주",
    "우b",
)


class KRUniverseLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class KRUniverseSnapshot:
    symbols: list[SymbolSignal]
    meta: dict[str, Any]


class KRUniverseStore:
    def __init__(
        self,
        client: FMPClient | None,
        cache_path: Path | None = None,
        ttl_min: int | None = None,
        max_symbols: int | None = None,
        min_market_cap: float | None = None,
        min_volume: float | None = None,
        universe_mode: str | None = None,
    ) -> None:
        self.client = client
        self.cache_path = Path(
            cache_path
            or os.getenv("KR_UNIVERSE_CACHE_PATH")
            or DEFAULT_KR_UNIVERSE_CACHE_PATH
        )
        self.ttl_min = _to_int(
            os.getenv("KR_UNIVERSE_TTL_MIN"),
            ttl_min or DEFAULT_KR_UNIVERSE_TTL_MIN,
            lo=1,
            hi=1440,
        )
        self.max_symbols = _to_int(
            os.getenv("KR_UNIVERSE_MAX_SYMBOLS"),
            max_symbols or DEFAULT_KR_UNIVERSE_MAX_SYMBOLS,
            lo=200,
            hi=5000,
        )
        self.min_market_cap = _to_float(
            os.getenv("KR_UNIVERSE_MIN_MARKET_CAP"),
            min_market_cap if min_market_cap is not None else DEFAULT_KR_UNIVERSE_MIN_MARKET_CAP,
        )
        self.min_volume = _to_float(
            os.getenv("KR_UNIVERSE_MIN_VOLUME"),
            min_volume if min_volume is not None else DEFAULT_KR_UNIVERSE_MIN_VOLUME,
        )
        self.universe_mode = _normalize_universe_mode(
            str(os.getenv("KR_UNIVERSE_MODE") or universe_mode or DEFAULT_KR_UNIVERSE_MODE)
        )

    def load_symbols(self) -> KRUniverseSnapshot:
        cached_payload = self._read_cache_payload()
        cached_snapshot = _snapshot_from_payload(cached_payload)
        cache_stale = self._is_cache_stale(cached_snapshot.meta.get("fetched_at"))
        cached_mode_raw = str(cached_payload.get("universe_mode") or "").strip()
        cached_mode = _normalize_universe_mode(cached_mode_raw) if cached_mode_raw else ""
        mode_mismatch = (not cached_mode_raw) or (cached_mode != self.universe_mode)

        should_refresh = not cached_snapshot.symbols or cache_stale or mode_mismatch
        if should_refresh:
            if self.client is None and cached_snapshot.symbols:
                # Keep using real-data stale cache when live client is unavailable.
                return _with_source(cached_snapshot, "stale")
            try:
                live_snapshot = self._fetch_and_cache_live()
                return live_snapshot
            except Exception as exc:
                logger.warning("kr universe live refresh failed", exc_info=True)
                if cached_snapshot.symbols:
                    return _with_source(cached_snapshot, "stale")
                raise KRUniverseLoadError("UNIVERSE_LOAD_FAILED") from exc

        if cached_snapshot.symbols:
            return _with_source(cached_snapshot, "stale")
        raise KRUniverseLoadError("UNIVERSE_LOAD_FAILED:NO_CACHE")

    def read_cached_meta(self) -> dict[str, Any]:
        cached_payload = self._read_cache_payload()
        snapshot = _snapshot_from_payload(cached_payload)
        if snapshot.meta:
            meta = dict(snapshot.meta)
            meta["source"] = "stale"
            return meta
        return _default_meta(source="unavailable")

    def _fetch_and_cache_live(self) -> KRUniverseSnapshot:
        if self.client is None:
            raise KRUniverseLoadError("UNIVERSE_LOAD_FAILED:NO_FMP_CLIENT")

        rows = self.client.fetch_us_stock_list()
        candidates = self._normalize_candidates(rows)
        raw_count = len(rows)
        if self.universe_mode == KR_UNIVERSE_MODE_INDEX_BLEND:
            picked, selection_meta = self._select_kospi_kosdaq(candidates)
        else:
            candidates.sort(key=lambda item: float(item["liquidity_score"]), reverse=True)
            picked = candidates[: self.max_symbols]
            selection_meta = {
                "filtered_count": len(candidates),
                "kospi500_count": 0,
                "kosdaq200_count": 0,
            }
        symbols = self._candidates_to_symbols(picked)
        if not symbols:
            raise KRUniverseLoadError("UNIVERSE_EMPTY_AFTER_FILTER")

        payload = {
            "scope": "KR",
            "source": "live",
            "source_provider": "fmp",
            "universe_mode": self.universe_mode,
            "ranking_basis": "market_cap",
            "raw_count": raw_count,
            "filtered_count": int(selection_meta.get("filtered_count") or len(symbols)),
            "selected_count": len(symbols),
            "kospi500_count": int(selection_meta.get("kospi500_count") or 0),
            "kosdaq200_count": int(selection_meta.get("kosdaq200_count") or 0),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "symbols": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "sector": item.sector,
                    "daily_return_pct": item.daily_return_pct,
                    "momentum_20d": item.momentum_20d,
                    "ai_factor": item.ai_factor,
                }
                for item in symbols
            ],
        }
        self._write_cache_payload(payload)
        return _snapshot_from_payload(payload)

    def _normalize_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for row in rows:
            candidate = self._to_candidate(row)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def _to_candidate(self, row: dict[str, Any]) -> dict[str, Any] | None:
        raw_symbol = str(row.get("symbol") or "").upper().strip()
        if not raw_symbol or SYMBOL_RE.fullmatch(raw_symbol) is None:
            return None
        symbol = raw_symbol.split(".")[0]
        if not symbol.isdigit() or len(symbol) != 6:
            return None

        market = _normalize_market(row, raw_symbol)
        if market not in {"KOSPI", "KOSDAQ"}:
            return None
        if not _is_active(row):
            return None
        if _is_non_common_security(row):
            return None

        name = str(row.get("name") or symbol).strip()
        if _is_non_common_name(name):
            return None

        market_cap = _to_float(row.get("marketCap"), 0.0)
        volume = _to_float(row.get("volume"), 0.0)
        price = _to_float(row.get("price"), 0.0)
        if price <= 0:
            return None
        if market_cap > 0 and market_cap < self.min_market_cap:
            return None
        if volume > 0 and volume < self.min_volume:
            return None

        daily = _to_float(
            row.get("changesPercentage"),
            _to_float(row.get("changePercentage"), 0.0),
        )
        daily = max(-25.0, min(25.0, daily))
        momentum = max(-40.0, min(40.0, daily * 2.2))

        sector = str(row.get("sector") or row.get("industry") or "Unknown")
        liquidity_score = (
            math.log10(max(1.0, market_cap) + 1.0) * 0.6
            + math.log10(max(1.0, volume) + 1.0) * 0.3
            + math.log10(price + 1.0) * 0.1
        )
        return {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "market": market,
            "market_cap": market_cap,
            "daily_return_pct": round(daily, 4),
            "momentum_20d": round(momentum, 4),
            "liquidity_score": liquidity_score,
        }

    def _select_kospi_kosdaq(
        self, candidates: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        by_symbol: dict[str, dict[str, Any]] = {}
        for row in candidates:
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            current = by_symbol.get(symbol)
            if current is None or float(row.get("liquidity_score", 0.0)) > float(
                current.get("liquidity_score", 0.0)
            ):
                by_symbol[symbol] = row

        kospi_rows = [
            row for row in by_symbol.values() if str(row.get("market") or "") == "KOSPI"
        ]
        kosdaq_rows = [
            row for row in by_symbol.values() if str(row.get("market") or "") == "KOSDAQ"
        ]

        kospi_rows.sort(
            key=lambda item: (
                -float(item.get("market_cap", 0.0)),
                -float(item.get("liquidity_score", 0.0)),
                str(item.get("symbol") or ""),
            )
        )
        kosdaq_rows.sort(
            key=lambda item: (
                -float(item.get("market_cap", 0.0)),
                -float(item.get("liquidity_score", 0.0)),
                str(item.get("symbol") or ""),
            )
        )
        kospi500 = kospi_rows[:500]
        kosdaq200 = kosdaq_rows[:200]

        union: dict[str, dict[str, Any]] = {}
        for row in kospi500:
            union[str(row["symbol"])] = row
        for row in kosdaq200:
            union[str(row["symbol"])] = row

        selected = list(union.values())
        selected.sort(
            key=lambda item: (
                -float(item.get("market_cap", 0.0)),
                -float(item.get("liquidity_score", 0.0)),
                str(item.get("symbol") or ""),
            )
        )
        if len(selected) > self.max_symbols:
            selected = selected[: self.max_symbols]

        return selected, {
            "filtered_count": len(selected),
            "kospi500_count": len(kospi500),
            "kosdaq200_count": len(kosdaq200),
        }

    def _candidates_to_symbols(self, picked: list[dict[str, Any]]) -> list[SymbolSignal]:
        symbols: list[SymbolSignal] = []
        size = len(picked)
        for idx, row in enumerate(picked):
            if size <= 1:
                ai_factor = 0.65
            else:
                ai_factor = 0.95 - (idx / (size - 1)) * 0.6
            symbols.append(
                SymbolSignal(
                    symbol=str(row["symbol"]),
                    name=str(row["name"]),
                    sector=str(row.get("sector") or "Unknown"),
                    daily_return_pct=float(row.get("daily_return_pct", 0.0)),
                    momentum_20d=float(row.get("momentum_20d", 0.0)),
                    ai_factor=round(max(0.35, min(0.95, ai_factor)), 4),
                )
            )
        return symbols

    def _is_cache_stale(self, fetched_at: Any) -> bool:
        stamp = _parse_iso_datetime(fetched_at)
        if stamp is None:
            return True
        return datetime.now(timezone.utc) - stamp > timedelta(minutes=self.ttl_min)

    def _read_cache_payload(self) -> dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(
                "failed to read kr universe cache path=%s",
                self.cache_path,
                exc_info=True,
            )
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_cache_payload(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _snapshot_from_payload(payload: dict[str, Any]) -> KRUniverseSnapshot:
    raw_symbols = payload.get("symbols")
    symbols: list[SymbolSignal] = []
    if isinstance(raw_symbols, list):
        for row in raw_symbols:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            symbols.append(
                SymbolSignal(
                    symbol=symbol,
                    name=str(row.get("name") or symbol),
                    sector=str(row.get("sector") or "Unknown"),
                    daily_return_pct=_to_float(row.get("daily_return_pct"), 0.0),
                    momentum_20d=_to_float(row.get("momentum_20d"), 0.0),
                    ai_factor=max(0.0, min(1.0, _to_float(row.get("ai_factor"), 0.5))),
                )
            )

    meta = {
        "scope": "KR",
        "source": str(payload.get("source") or ("stale" if symbols else "unavailable")),
        "source_provider": str(payload.get("source_provider") or ""),
        "universe_mode": _normalize_universe_mode(
            str(payload.get("universe_mode") or DEFAULT_KR_UNIVERSE_MODE)
        ),
        "ranking_basis": str(payload.get("ranking_basis") or ""),
        "raw_count": _to_int(payload.get("raw_count"), len(symbols), lo=0, hi=10_000_000),
        "filtered_count": _to_int(
            payload.get("filtered_count"), len(symbols), lo=0, hi=10_000_000
        ),
        "selected_count": _to_int(
            payload.get("selected_count"), len(symbols), lo=0, hi=10_000_000
        ),
        "kospi500_count": _to_int(payload.get("kospi500_count"), 0, lo=0, hi=10_000_000),
        "kosdaq200_count": _to_int(payload.get("kosdaq200_count"), 0, lo=0, hi=10_000_000),
        "fetched_at": str(payload.get("fetched_at") or ""),
    }
    return KRUniverseSnapshot(symbols=symbols, meta=meta)


def _with_source(snapshot: KRUniverseSnapshot, source: str) -> KRUniverseSnapshot:
    meta = dict(snapshot.meta)
    meta["source"] = source
    return KRUniverseSnapshot(symbols=list(snapshot.symbols), meta=meta)


def _default_meta(source: str) -> dict[str, Any]:
    return {
        "scope": "KR",
        "source": source,
        "source_provider": "",
        "universe_mode": DEFAULT_KR_UNIVERSE_MODE,
        "ranking_basis": "",
        "raw_count": 0,
        "filtered_count": 0,
        "selected_count": 0,
        "kospi500_count": 0,
        "kosdaq200_count": 0,
        "fetched_at": "",
    }


def _normalize_market(row: dict[str, Any], raw_symbol: str) -> str:
    text = str(row.get("exchangeShortName") or row.get("exchange") or "").upper().strip()
    if "KOSDAQ" in text or ".KQ" in raw_symbol:
        return "KOSDAQ"
    if "KOSPI" in text or "KRX" in text or ".KS" in raw_symbol or "KSE" in text:
        return "KOSPI"
    return ""


def _is_active(row: dict[str, Any]) -> bool:
    if "isActivelyTrading" not in row:
        return True
    return _to_bool(row.get("isActivelyTrading"), default=False)


def _is_non_common_security(row: dict[str, Any]) -> bool:
    if _to_bool(row.get("isEtf"), default=False):
        return True
    if _to_bool(row.get("isFund"), default=False):
        return True
    type_text = str(
        row.get("type") or row.get("assetType") or row.get("securityType") or ""
    ).lower().strip()
    if type_text and any(token in type_text for token in EXCLUDED_TYPE_KEYWORDS):
        return True
    return False


def _is_non_common_name(name: str) -> bool:
    lowered = f" {name.lower()} "
    return any(token in lowered for token in EXCLUDED_NAME_KEYWORDS)


def _normalize_universe_mode(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"KOSPI500_KOSDAQ200", "KOSPI500+KOSDAQ200", "KR_INDEX_BLEND"}:
        return KR_UNIVERSE_MODE_INDEX_BLEND
    if text in {"KR_TOP_LIQUIDITY", "KR_BROAD", "BROAD"}:
        return KR_UNIVERSE_MODE_LIQUIDITY
    return DEFAULT_KR_UNIVERSE_MODE


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _to_int(value: Any, default: int, *, lo: int, hi: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
