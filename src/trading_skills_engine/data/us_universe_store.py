from __future__ import annotations

import json
import logging
import math
import os
import re
from csv import DictReader
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from trading_skills_engine.core.models import SymbolSignal
from trading_skills_engine.data.fmp_client import FMPClient

logger = logging.getLogger(__name__)

DEFAULT_US_UNIVERSE_CACHE_PATH = Path("reports/cache/universe/us_universe.json")
DEFAULT_US_UNIVERSE_TTL_MIN = 60
DEFAULT_US_UNIVERSE_MAX_SYMBOLS = 2000
DEFAULT_US_UNIVERSE_MIN_MARKET_CAP = 500_000_000.0
DEFAULT_US_UNIVERSE_MIN_VOLUME = 100_000.0
DEFAULT_US_UNIVERSE_PUBLIC_FALLBACK = True
DEFAULT_US_UNIVERSE_MODE = "SP500_PLUS_NASDAQ_TOP500"
US_UNIVERSE_MODE_BROAD = "US_TOP_LIQUIDITY"
US_UNIVERSE_MODE_SP500_NASDAQ500 = "SP500_PLUS_NASDAQ_TOP500"

ALLOWED_EXCHANGES = {"NYSE", "NASDAQ", "AMEX"}
SYMBOL_RE = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")

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
INCLUDED_TYPE_KEYWORDS = ("stock", "common", "equity")
EXCLUDED_NAME_KEYWORDS = (
    " etf",
    " fund",
    " adr",
    "warrant",
    " right",
    " unit",
    " preferred",
    " bond",
    " note",
    " trust",
    " nextshares",
    " depositary",
)
PUBLIC_NASDAQ_TRADED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
PUBLIC_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
SP500_LIST_URLS = (
    "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv",
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
)


class USUniverseLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class USUniverseSnapshot:
    symbols: list[SymbolSignal]
    meta: dict[str, Any]


class USUniverseStore:
    def __init__(
        self,
        client: FMPClient | None,
        cache_path: Path | None = None,
        ttl_min: int | None = None,
        max_symbols: int | None = None,
        min_market_cap: float | None = None,
        min_volume: float | None = None,
        allow_public_fallback: bool | None = None,
        universe_mode: str | None = None,
    ) -> None:
        self.client = client
        self.cache_path = Path(os.getenv("US_UNIVERSE_CACHE_PATH") or cache_path or DEFAULT_US_UNIVERSE_CACHE_PATH)
        self.ttl_min = _to_int(os.getenv("US_UNIVERSE_TTL_MIN"), ttl_min or DEFAULT_US_UNIVERSE_TTL_MIN, lo=1, hi=1440)
        self.max_symbols = _to_int(
            os.getenv("US_UNIVERSE_MAX_SYMBOLS"),
            max_symbols or DEFAULT_US_UNIVERSE_MAX_SYMBOLS,
            lo=200,
            hi=10_000,
        )
        self.min_market_cap = _to_float(
            os.getenv("US_UNIVERSE_MIN_MARKET_CAP"),
            min_market_cap if min_market_cap is not None else DEFAULT_US_UNIVERSE_MIN_MARKET_CAP,
        )
        self.min_volume = _to_float(
            os.getenv("US_UNIVERSE_MIN_VOLUME"),
            min_volume if min_volume is not None else DEFAULT_US_UNIVERSE_MIN_VOLUME,
        )
        self.allow_public_fallback = _to_bool(
            os.getenv("US_UNIVERSE_PUBLIC_FALLBACK"),
            default=allow_public_fallback if allow_public_fallback is not None else DEFAULT_US_UNIVERSE_PUBLIC_FALLBACK,
        )
        self.universe_mode = _normalize_universe_mode(
            str(os.getenv("US_UNIVERSE_MODE") or universe_mode or DEFAULT_US_UNIVERSE_MODE)
        )
        self._sp500_symbols_cache: set[str] | None = None

    def load_symbols(self) -> USUniverseSnapshot:
        cached_payload = self._read_cache_payload()
        cached_snapshot = _snapshot_from_payload(cached_payload)
        cache_stale = self._is_cache_stale(cached_snapshot.meta.get("fetched_at"))
        cached_mode_raw = str(cached_payload.get("universe_mode") or "").strip()
        cached_mode = _normalize_universe_mode(cached_mode_raw) if cached_mode_raw else ""
        mode_mismatch = (not cached_mode_raw) or (cached_mode != self.universe_mode)

        should_refresh = not cached_snapshot.symbols or cache_stale or mode_mismatch
        if should_refresh:
            try:
                live_snapshot = self._fetch_and_cache_live()
                return live_snapshot
            except Exception as exc:
                logger.warning("us universe live refresh failed", exc_info=True)
                if cached_snapshot.symbols:
                    return _with_source(cached_snapshot, "stale")
                raise USUniverseLoadError("UNIVERSE_LOAD_FAILED") from exc

        if cached_snapshot.symbols:
            return _with_source(cached_snapshot, "stale")

        if self.client is None and not self.allow_public_fallback:
            raise USUniverseLoadError("UNIVERSE_LOAD_FAILED:NO_FMP_CLIENT_AND_NO_CACHE")
        raise USUniverseLoadError("UNIVERSE_LOAD_FAILED:NO_CACHE")

    def read_cached_meta(self) -> dict[str, Any]:
        cached_payload = self._read_cache_payload()
        snapshot = _snapshot_from_payload(cached_payload)
        if snapshot.meta:
            meta = dict(snapshot.meta)
            meta["source"] = "stale"
            return meta
        return _default_meta(source="unavailable")

    def _fetch_and_cache_live(self) -> USUniverseSnapshot:
        symbols: list[SymbolSignal]
        raw_count: int
        filtered_count: int
        source_provider = "fmp"
        ranking_basis = "market_cap"
        sp500_count = 0
        nasdaq_top500_count = 0

        if self.client is not None:
            try:
                raw_rows = self.client.fetch_us_stock_list()
                candidates = self._normalize_candidates(raw_rows)
                raw_count = len(raw_rows)
                if self.universe_mode == US_UNIVERSE_MODE_SP500_NASDAQ500:
                    selected, selection_meta = self._select_sp500_plus_nasdaq_top500(candidates)
                    filtered_count = selection_meta["filtered_count"]
                    sp500_count = selection_meta["sp500_count"]
                    nasdaq_top500_count = selection_meta["nasdaq_top500_count"]
                else:
                    candidates.sort(key=lambda item: float(item["liquidity_score"]), reverse=True)
                    filtered_count = len(candidates)
                    selected = candidates[: self.max_symbols]
                symbols = self._candidates_to_symbols(selected)
            except HTTPError as exc:
                if exc.code not in {402, 403}:
                    raise
                if not self.allow_public_fallback:
                    raise
                logger.warning("fmp stock-list unavailable status=%s. falling back to public symbol directory", exc.code)
                symbols, raw_count, filtered_count, selection_meta = self._load_public_universe()
                source_provider = "public_symbol_directory"
                ranking_basis = "liquidity_proxy"
                sp500_count = int(selection_meta.get("sp500_count") or 0)
                nasdaq_top500_count = int(selection_meta.get("nasdaq_top500_count") or 0)
            except Exception:
                if not self.allow_public_fallback:
                    raise
                logger.warning("fmp stock-list unavailable. falling back to public symbol directory", exc_info=True)
                symbols, raw_count, filtered_count, selection_meta = self._load_public_universe()
                source_provider = "public_symbol_directory"
                ranking_basis = "liquidity_proxy"
                sp500_count = int(selection_meta.get("sp500_count") or 0)
                nasdaq_top500_count = int(selection_meta.get("nasdaq_top500_count") or 0)
        else:
            if not self.allow_public_fallback:
                raise USUniverseLoadError("UNIVERSE_LOAD_FAILED:NO_FMP_CLIENT")
            symbols, raw_count, filtered_count, selection_meta = self._load_public_universe()
            source_provider = "public_symbol_directory"
            ranking_basis = "liquidity_proxy"
            sp500_count = int(selection_meta.get("sp500_count") or 0)
            nasdaq_top500_count = int(selection_meta.get("nasdaq_top500_count") or 0)

        if not symbols:
            raise USUniverseLoadError("UNIVERSE_EMPTY_AFTER_FILTER")

        payload = {
            "scope": "US",
            "source": "live",
            "source_provider": source_provider,
            "universe_mode": self.universe_mode,
            "ranking_basis": ranking_basis,
            "raw_count": raw_count,
            "filtered_count": filtered_count,
            "selected_count": len(symbols),
            "sp500_count": sp500_count,
            "nasdaq_top500_count": nasdaq_top500_count,
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

    def _load_public_universe(self) -> tuple[list[SymbolSignal], int, int, dict[str, int]]:
        rows = self._fetch_public_symbol_rows()
        raw_count = len(rows)

        candidates: list[dict[str, Any]] = []
        for row in rows:
            candidate = self._public_row_to_candidate(row)
            if candidate is not None:
                candidates.append(candidate)

        if self.universe_mode == US_UNIVERSE_MODE_SP500_NASDAQ500:
            picked, selection_meta = self._select_sp500_plus_nasdaq_top500(candidates)
            filtered_count = selection_meta["filtered_count"]
        else:
            candidates.sort(key=lambda item: float(item["liquidity_score"]), reverse=True)
            filtered_count = len(candidates)
            picked = candidates[: self.max_symbols]
            selection_meta = {"sp500_count": 0, "nasdaq_top500_count": 0, "filtered_count": filtered_count}

        symbols = self._candidates_to_symbols(picked)
        return symbols, raw_count, filtered_count, selection_meta

    def _fetch_public_symbol_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        rows.extend(_parse_pipe_table(_download_text(PUBLIC_NASDAQ_TRADED_URL), "nasdaqtraded"))
        rows.extend(_parse_pipe_table(_download_text(PUBLIC_OTHER_LISTED_URL), "otherlisted"))
        return rows

    def _public_row_to_candidate(self, row: dict[str, str]) -> dict[str, Any] | None:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol or SYMBOL_RE.fullmatch(symbol) is None:
            return None

        exchange = str(row.get("exchange") or "").upper().strip()
        if exchange not in ALLOWED_EXCHANGES:
            return None

        if str(row.get("is_etf") or "").upper() == "Y":
            return None
        if str(row.get("is_test_issue") or "").upper() == "Y":
            return None

        name = str(row.get("name") or symbol).strip()
        if _is_non_common_name(name):
            return None

        exchange_weight = {"NASDAQ": 3.0, "NYSE": 2.7, "AMEX": 2.2}.get(exchange, 1.5)
        symbol_quality = 1.0
        if "." in symbol or "-" in symbol:
            symbol_quality -= 0.25
        if len(symbol) > 4:
            symbol_quality -= 0.15

        liquidity_score = exchange_weight + symbol_quality
        return {
            "symbol": symbol,
            "name": name,
            "sector": "Unknown",
            "exchange": exchange,
            "market_cap": 0.0,
            "liquidity_score": liquidity_score,
        }

    def _normalize_candidates(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for row in rows:
            candidate = self._to_candidate(row)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

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
                    sector=str(row["sector"]),
                    daily_return_pct=float(row.get("daily_return_pct", 0.0)),
                    momentum_20d=float(row.get("momentum_20d", 0.0)),
                    ai_factor=round(max(0.35, min(0.95, ai_factor)), 4),
                )
            )
        return symbols

    def _select_sp500_plus_nasdaq_top500(self, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
        sp500_symbols = self._fetch_sp500_symbols()

        by_symbol: dict[str, dict[str, Any]] = {}
        for row in candidates:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            current = by_symbol.get(symbol)
            if current is None or float(row.get("liquidity_score", 0.0)) > float(current.get("liquidity_score", 0.0)):
                by_symbol[symbol] = row

        sp500_rows = [row for sym, row in by_symbol.items() if sym in sp500_symbols]
        nasdaq_rows = [row for row in by_symbol.values() if str(row.get("exchange") or "") == "NASDAQ"]
        nasdaq_rows.sort(
            key=lambda item: (
                -float(item.get("market_cap", 0.0)),
                -float(item.get("liquidity_score", 0.0)),
                str(item.get("symbol") or ""),
            )
        )
        nasdaq_top500 = nasdaq_rows[:500]

        union: dict[str, dict[str, Any]] = {}
        for row in sp500_rows:
            union[str(row["symbol"])] = row
        for row in nasdaq_top500:
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
            "sp500_count": len(sp500_rows),
            "nasdaq_top500_count": len(nasdaq_top500),
            "filtered_count": len(selected),
        }

    def _fetch_sp500_symbols(self) -> set[str]:
        if self._sp500_symbols_cache is not None:
            return set(self._sp500_symbols_cache)

        for url in SP500_LIST_URLS:
            try:
                text = _download_text(url)
                parsed = _parse_sp500_symbols_csv(text)
                if parsed:
                    self._sp500_symbols_cache = set(parsed)
                    return set(parsed)
            except Exception:
                logger.warning("failed to fetch sp500 symbols url=%s", url, exc_info=True)
                continue
        raise USUniverseLoadError("UNIVERSE_LOAD_FAILED:SP500_LIST_FETCH_FAILED")

    def _normalize_rows(self, rows: list[dict[str, Any]]) -> tuple[list[SymbolSignal], int, int]:
        candidates = self._normalize_candidates(rows)
        candidates.sort(key=lambda item: float(item["liquidity_score"]), reverse=True)
        filtered_count = len(candidates)
        picked = candidates[: self.max_symbols]
        symbols = self._candidates_to_symbols(picked)
        return symbols, len(rows), filtered_count

    def _to_candidate(self, row: dict[str, Any]) -> dict[str, Any] | None:
        symbol = str(row.get("symbol") or "").upper().strip()
        if not symbol or SYMBOL_RE.fullmatch(symbol) is None:
            return None

        exchange = _normalize_exchange(row)
        if exchange not in ALLOWED_EXCHANGES:
            return None

        if not _is_active(row):
            return None
        if _is_non_common_security(row):
            return None

        market_cap = _to_float(row.get("marketCap"), 0.0)
        volume = _to_float(row.get("volume"), 0.0)
        price = _to_float(row.get("price"), 0.0)
        if market_cap < self.min_market_cap:
            return None
        if volume < self.min_volume:
            return None
        if price <= 0:
            return None

        daily = _to_float(row.get("changesPercentage"), _to_float(row.get("changePercentage"), 0.0))
        daily = max(-25.0, min(25.0, daily))
        momentum = max(-40.0, min(40.0, daily * 2.2))

        name = str(row.get("name") or symbol)
        sector = str(row.get("sector") or row.get("industry") or "Unknown")
        liquidity_score = (
            math.log10(market_cap + 1.0) * 0.58
            + math.log10(volume + 1.0) * 0.34
            + math.log10(price + 1.0) * 0.08
        )
        return {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "exchange": exchange,
            "market_cap": market_cap,
            "daily_return_pct": round(daily, 4),
            "momentum_20d": round(momentum, 4),
            "liquidity_score": liquidity_score,
        }

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
            logger.warning("failed to read us universe cache path=%s", self.cache_path, exc_info=True)
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

    def _write_cache_payload(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _snapshot_from_payload(payload: dict[str, Any]) -> USUniverseSnapshot:
    raw_symbols = payload.get("symbols")
    symbols: list[SymbolSignal] = []
    if isinstance(raw_symbols, list):
        for row in raw_symbols:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").upper().strip()
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
        "scope": "US",
        "source": str(payload.get("source") or ("stale" if symbols else "unavailable")),
        "source_provider": str(payload.get("source_provider") or ""),
        "universe_mode": _normalize_universe_mode(str(payload.get("universe_mode") or DEFAULT_US_UNIVERSE_MODE)),
        "ranking_basis": str(payload.get("ranking_basis") or ""),
        "raw_count": _to_int(payload.get("raw_count"), len(symbols), lo=0, hi=10_000_000),
        "filtered_count": _to_int(payload.get("filtered_count"), len(symbols), lo=0, hi=10_000_000),
        "selected_count": _to_int(payload.get("selected_count"), len(symbols), lo=0, hi=10_000_000),
        "sp500_count": _to_int(payload.get("sp500_count"), 0, lo=0, hi=10_000_000),
        "nasdaq_top500_count": _to_int(payload.get("nasdaq_top500_count"), 0, lo=0, hi=10_000_000),
        "fetched_at": str(payload.get("fetched_at") or ""),
    }
    return USUniverseSnapshot(symbols=symbols, meta=meta)


def _with_source(snapshot: USUniverseSnapshot, source: str) -> USUniverseSnapshot:
    meta = dict(snapshot.meta)
    meta["source"] = source
    return USUniverseSnapshot(symbols=list(snapshot.symbols), meta=meta)


def _default_meta(source: str) -> dict[str, Any]:
    return {
        "scope": "US",
        "source": source,
        "source_provider": "",
        "universe_mode": DEFAULT_US_UNIVERSE_MODE,
        "ranking_basis": "",
        "raw_count": 0,
        "filtered_count": 0,
        "selected_count": 0,
        "sp500_count": 0,
        "nasdaq_top500_count": 0,
        "fetched_at": "",
    }


def _normalize_exchange(row: dict[str, Any]) -> str:
    raw = str(row.get("exchangeShortName") or row.get("exchange") or "").upper().strip()
    if "NASDAQ" in raw:
        return "NASDAQ"
    if "NYSE" in raw:
        return "NYSE"
    if "AMEX" in raw:
        return "AMEX"
    return raw


def _is_active(row: dict[str, Any]) -> bool:
    if "isActivelyTrading" not in row:
        return True
    return _to_bool(row.get("isActivelyTrading"), default=False)


def _is_non_common_security(row: dict[str, Any]) -> bool:
    if _to_bool(row.get("isEtf"), default=False):
        return True
    if _to_bool(row.get("isFund"), default=False):
        return True

    type_text = str(row.get("type") or row.get("assetType") or row.get("securityType") or "").lower().strip()
    if type_text:
        if any(token in type_text for token in EXCLUDED_TYPE_KEYWORDS):
            return True
        if not any(token in type_text for token in INCLUDED_TYPE_KEYWORDS):
            return True
    return False


def _is_non_common_name(name: str) -> bool:
    lowered = f" {name.lower()} "
    return any(token in lowered for token in EXCLUDED_NAME_KEYWORDS)


def _download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})
    with urlopen(req, timeout=20) as response:
        return response.read().decode("utf-8", errors="ignore")


def _parse_pipe_table(text: str, source_name: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    headers = [item.strip() for item in lines[0].split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            break
        parts = [item.strip() for item in line.split("|")]
        if len(parts) < len(headers):
            continue
        record = {headers[idx]: parts[idx] for idx in range(len(headers))}
        normalized = _normalize_public_row(source_name, record)
        if normalized is not None:
            rows.append(normalized)
    return rows


def _normalize_public_row(source_name: str, record: dict[str, str]) -> dict[str, str] | None:
    if source_name == "nasdaqtraded":
        listing_exchange = str(record.get("Listing Exchange") or "").upper().strip()
        exchange = {"Q": "NASDAQ", "N": "NYSE", "A": "AMEX"}.get(listing_exchange, "")
        symbol = str(record.get("Symbol") or "").upper().strip()
        if not symbol:
            return None
        return {
            "symbol": symbol,
            "name": str(record.get("Security Name") or symbol).strip(),
            "exchange": exchange,
            "is_etf": str(record.get("ETF") or "").upper().strip(),
            "is_test_issue": str(record.get("Test Issue") or "").upper().strip(),
        }

    if source_name == "otherlisted":
        exchange_code = str(record.get("Exchange") or "").upper().strip()
        exchange = {"N": "NYSE", "A": "AMEX"}.get(exchange_code, "")
        symbol = str(record.get("ACT Symbol") or "").upper().strip()
        if not symbol:
            return None
        return {
            "symbol": symbol,
            "name": str(record.get("Security Name") or symbol).strip(),
            "exchange": exchange,
            "is_etf": str(record.get("ETF") or "").upper().strip(),
            "is_test_issue": str(record.get("Test Issue") or "").upper().strip(),
        }
    return None


def _parse_sp500_symbols_csv(text: str) -> set[str]:
    symbols: set[str] = set()
    reader = DictReader(StringIO(text))
    for row in reader:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("Symbol") or row.get("symbol") or "").strip().upper()
        symbol = raw.replace(".", "-")
        if symbol and SYMBOL_RE.fullmatch(symbol):
            symbols.add(symbol)
    return symbols


def _normalize_universe_mode(value: str) -> str:
    text = str(value or "").strip().upper()
    if text in {"SP500_PLUS_NASDAQ_TOP500", "SP500_NASDAQ500", "SP500+NASDAQ500"}:
        return US_UNIVERSE_MODE_SP500_NASDAQ500
    if text in {"US_TOP_LIQUIDITY", "BROAD", "US_BROAD"}:
        return US_UNIVERSE_MODE_BROAD
    return DEFAULT_US_UNIVERSE_MODE


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
