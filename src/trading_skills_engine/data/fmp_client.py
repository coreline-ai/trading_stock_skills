from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_skills_engine.config.env import ensure_project_env_loaded
from trading_skills_engine.config.fmp_runtime import FMPRuntimeSettingsStore
from trading_skills_engine.data.fmp_usage_tracker import FMPUsageTracker


@dataclass(frozen=True)
class FMPClient:
    api_key: str
    base_url: str = "https://financialmodelingprep.com/stable"
    usage_tracker: FMPUsageTracker | None = None

    @classmethod
    def from_env(cls) -> "FMPClient | None":
        ensure_project_env_loaded()
        key = os.getenv("FMP_API_KEY")
        if not key:
            return None
        runtime = FMPRuntimeSettingsStore().read()
        if not runtime.enabled:
            return None
        return cls(
            api_key=key,
            usage_tracker=FMPUsageTracker(daily_limit=runtime.daily_limit),
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.usage_tracker and not self.usage_tracker.try_consume():
            raise RuntimeError("FMP_DAILY_LIMIT_REACHED")

        query = {"apikey": self.api_key}
        if params:
            query.update(params)
        normalized = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized}?{urlencode(query)}"
        req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})

        for attempt in range(3):
            try:
                with urlopen(req, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in {429, 500} and attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise
            except URLError:
                if attempt < 2:
                    time.sleep(0.4 * (attempt + 1))
                    continue
                raise

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        rows: list[dict[str, Any]] = []
        for symbol in symbols[:50]:
            try:
                data = self._get("/quote", {"symbol": symbol})
            except Exception:
                continue
            if isinstance(data, list) and data and isinstance(data[0], dict):
                rows.append(data[0])
        return rows
