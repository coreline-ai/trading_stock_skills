from __future__ import annotations

from typing import Any

from trading_skills_engine.data.fmp_client import FMPClient


class FMPNewsClient:
    def __init__(self, client: FMPClient) -> None:
        self.client = client

    @classmethod
    def from_env(cls) -> "FMPNewsClient | None":
        client = FMPClient.from_env()
        if not client:
            return None
        return cls(client)

    def get_market_news(self, limit: int = 80) -> list[dict[str, Any]]:
        page_size = max(1, min(limit, 100))
        data = self.client._get("/fmp-articles", {"page": 0, "limit": page_size})
        if not isinstance(data, list):
            return []

        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "title": str(item.get("title") or ""),
                    "publishedDate": str(item.get("date") or ""),
                    "site": str(item.get("site") or "FMP"),
                    "url": str(item.get("link") or ""),
                    "tickers": str(item.get("tickers") or ""),
                }
            )
        return rows

    def get_quote(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get("/quote", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_profile(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get("/profile", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_key_metrics_ttm(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get("/key-metrics-ttm", {"symbol": ticker})
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_peers(self, ticker: str) -> list[str]:
        data = self.client._get("/stock-peers", {"symbol": ticker})
        if isinstance(data, list):
            peers: list[str] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").upper().strip()
                if symbol and symbol not in peers:
                    peers.append(symbol)
            return peers
        return []
