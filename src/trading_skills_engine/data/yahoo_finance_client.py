from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class YahooFinanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class YahooFinanceClient:
    base_url: str = "https://query1.finance.yahoo.com"
    timeout_sec: int = 4

    def fetch_quote(self, symbol: str) -> dict[str, Any]:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            raise YahooFinanceError("YAHOO_INVALID_SYMBOL")

        query = urlencode({"symbols": normalized})
        url = f"{self.base_url}/v7/finance/quote?{query}"
        req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})
        try:
            with urlopen(req, timeout=self.timeout_sec) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise YahooFinanceError(f"YAHOO_HTTP_{exc.code}") from exc
        except URLError as exc:
            raise YahooFinanceError("YAHOO_NETWORK_ERROR") from exc
        except Exception as exc:
            raise YahooFinanceError("YAHOO_PARSE_ERROR") from exc

        results = (
            payload.get("quoteResponse", {}).get("result", [])
            if isinstance(payload, dict)
            else []
        )
        if not results or not isinstance(results[0], dict):
            raise YahooFinanceError("YAHOO_SYMBOL_NOT_FOUND")
        row = results[0]

        def _num(key: str) -> float | None:
            raw = row.get(key)
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        metrics = {
            "price": _num("regularMarketPrice"),
            "change_pct": _num("regularMarketChangePercent"),
            "volume": _num("regularMarketVolume"),
            "market_cap": _num("marketCap"),
            "trailing_pe": _num("trailingPE"),
            "fifty_two_week_high": _num("fiftyTwoWeekHigh"),
            "fifty_two_week_low": _num("fiftyTwoWeekLow"),
            "exchange": str(row.get("fullExchangeName") or row.get("exchange") or ""),
            "currency": str(row.get("currency") or ""),
        }
        return {
            "source": "yahoo",
            "url": f"https://finance.yahoo.com/quote/{normalized}",
            "metrics": metrics,
        }
