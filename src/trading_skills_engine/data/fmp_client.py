from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen


@dataclass(frozen=True)
class FMPClient:
    api_key: str
    base_url: str = "https://financialmodelingprep.com/api/v3"

    @classmethod
    def from_env(cls) -> "FMPClient | None":
        key = os.getenv("FMP_API_KEY")
        if not key:
            return None
        return cls(api_key=key)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = {"apikey": self.api_key}
        if params:
            query.update(params)
        url = f"{self.base_url}{path}?{urlencode(query)}"
        with urlopen(url, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        joined = ",".join(symbols)
        data = self._get(f"/quote/{joined}")
        return data if isinstance(data, list) else []
