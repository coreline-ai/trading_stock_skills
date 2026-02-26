from __future__ import annotations

from datetime import date
from typing import Any

from trading_skills_engine.data.fmp_client import FMPClient


class FMPCalendarClient:
    def __init__(self, client: FMPClient) -> None:
        self.client = client

    @classmethod
    def from_env(cls) -> "FMPCalendarClient | None":
        client = FMPClient.from_env()
        if not client:
            return None
        return cls(client)

    def get_economic_calendar(self, start: date, end: date, country: str = "US") -> list[dict[str, Any]]:
        data = self.client._get(
            "/economic_calendar",
            {"from": start.isoformat(), "to": end.isoformat(), "country": country},
        )
        return data if isinstance(data, list) else []

    def get_earnings_calendar(self, start: date, end: date) -> list[dict[str, Any]]:
        data = self.client._get(
            "/earning_calendar",
            {"from": start.isoformat(), "to": end.isoformat()},
        )
        if isinstance(data, list):
            return data
        # fallback endpoint variation
        data_alt = self.client._get(
            "/earnings-calendar",
            {"from": start.isoformat(), "to": end.isoformat()},
        )
        return data_alt if isinstance(data_alt, list) else []
