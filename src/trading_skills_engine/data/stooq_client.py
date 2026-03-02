from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class StooqError(RuntimeError):
    pass


@dataclass(frozen=True)
class StooqClient:
    base_url: str = "https://stooq.com"
    timeout_sec: int = 4

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise StooqError("STOOQ_INVALID_SYMBOL")
        stooq_symbol = _to_stooq_symbol(normalized)
        url = f"{self.base_url}/q/l/?s={stooq_symbol}&i=d"
        req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})

        try:
            with urlopen(req, timeout=self.timeout_sec) as response:
                text = response.read().decode("utf-8", errors="ignore")
        except HTTPError as exc:
            raise StooqError(f"STOOQ_HTTP_{exc.code}") from exc
        except URLError as exc:
            raise StooqError("STOOQ_NETWORK_ERROR") from exc
        except Exception as exc:
            raise StooqError("STOOQ_PARSE_ERROR") from exc

        row = _parse_quote_row(text)
        close_raw = str(row.get("Close") or "").strip()
        if not close_raw or close_raw.upper() == "N/D":
            raise StooqError("STOOQ_SYMBOL_NOT_FOUND")

        def _num(key: str) -> float | None:
            raw = str(row.get(key) or "").strip()
            if not raw or raw.upper() == "N/D":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        metrics: dict[str, Any] = {
            "date": str(row.get("Date") or ""),
            "open": _num("Open"),
            "high": _num("High"),
            "low": _num("Low"),
            "close": _num("Close"),
            "volume": _num("Volume"),
        }
        return {
            "source": "stooq",
            "url": url,
            "metrics": metrics,
        }


def _to_stooq_symbol(normalized: str) -> str:
    upper = str(normalized or "").strip().upper()
    if "." in upper:
        return upper.lower()
    if upper.isdigit() and len(upper) == 6:
        return f"{upper}.kr"
    return f"{upper}.us"


def _parse_quote_row(csv_text: str) -> dict[str, str]:
    text = str(csv_text or "").strip()
    if not text:
        raise StooqError("STOOQ_NO_ROWS")

    dict_rows = list(csv.DictReader(StringIO(text)))
    if dict_rows and isinstance(dict_rows[0], dict) and "Close" in dict_rows[0]:
        return {str(k): str(v) for k, v in dict_rows[0].items()}

    rows = [row for row in csv.reader(StringIO(text)) if row]
    if not rows:
        raise StooqError("STOOQ_NO_ROWS")

    first = [str(item).strip() for item in rows[0]]
    has_header = bool(first and first[0].lower() == "symbol")
    if has_header:
        if len(rows) < 2:
            raise StooqError("STOOQ_NO_ROWS")
        values = [str(item).strip() for item in rows[1]]
    else:
        values = first

    if len(values) < 8:
        raise StooqError("STOOQ_NO_ROWS")

    return {
        "Symbol": values[0],
        "Date": values[1],
        "Time": values[2] if len(values) > 2 else "",
        "Open": values[3] if len(values) > 3 else "",
        "High": values[4] if len(values) > 4 else "",
        "Low": values[5] if len(values) > 5 else "",
        "Close": values[6] if len(values) > 6 else "",
        "Volume": values[7] if len(values) > 7 else "",
    }
