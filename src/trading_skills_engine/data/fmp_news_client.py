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
        data = self.client._get("/stock_news", {"limit": limit})
        return data if isinstance(data, list) else []

    def get_quote(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get(f"/quote/{ticker}")
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_profile(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get(f"/profile/{ticker}")
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_key_metrics_ttm(self, ticker: str) -> dict[str, Any] | None:
        data = self.client._get(f"/key-metrics-ttm/{ticker}")
        if isinstance(data, list) and data:
            return data[0] if isinstance(data[0], dict) else None
        return None

    def get_peers(self, ticker: str) -> list[str]:
        data = self.client._get("/stock_peers", {"symbol": ticker})
        if isinstance(data, list) and data and isinstance(data[0], dict):
            peers = data[0].get("peersList")
            if isinstance(peers, list):
                return [str(item) for item in peers]
        return []
