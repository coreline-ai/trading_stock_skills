from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_skills_engine.config.env import ensure_project_env_loaded
from trading_skills_engine.config.fmp_runtime import FMPRuntimeSettingsStore
from trading_skills_engine.data.fmp_usage_tracker import FMPUsageTracker

DEFAULT_FMP_RETRY_DELAYS = (1.0, 2.0, 4.0)
DEFAULT_FMP_RATE_LIMIT_COOLDOWN_SEC = 180
DEFAULT_FMP_RATE_LIMIT_STATE_PATH = Path("reports/runtime/fmp_rate_limit_state.json")


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
        if _is_rate_limited_now():
            raise RuntimeError("FMP_RATE_LIMIT_COOLDOWN")

        if self.usage_tracker and not self.usage_tracker.try_consume():
            raise RuntimeError("FMP_DAILY_LIMIT_REACHED")

        query = {"apikey": self.api_key}
        if params:
            query.update(params)
        normalized = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized}?{urlencode(query)}"
        req = Request(url, headers={"User-Agent": "trading-skills-engine/2.0"})
        retry_delays = _retry_delays()

        for attempt in range(len(retry_delays) + 1):
            try:
                with urlopen(req, timeout=8) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code == 429:
                    _mark_rate_limited_now()
                    if attempt < len(retry_delays):
                        time.sleep(retry_delays[attempt])
                        continue
                    raise RuntimeError("FMP_HTTP_429")
                if exc.code == 500 and attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
                    continue
                raise
            except URLError:
                if attempt < len(retry_delays):
                    time.sleep(retry_delays[attempt])
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

    def fetch_us_stock_list(self) -> list[dict[str, Any]]:
        data = self._get("/stock-list")
        if not isinstance(data, list):
            raise RuntimeError("FMP_STOCK_LIST_INVALID")
        rows: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict):
                rows.append(item)
        return rows


def _retry_delays() -> tuple[float, ...]:
    raw = str(os.getenv("FMP_HTTP_RETRY_DELAYS_SEC", "")).strip()
    if not raw:
        return DEFAULT_FMP_RETRY_DELAYS
    values: list[float] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = float(token)
        except ValueError:
            continue
        if value > 0:
            values.append(value)
    return tuple(values) or DEFAULT_FMP_RETRY_DELAYS


def _rate_limit_state_path() -> Path:
    raw = os.getenv("FMP_RATE_LIMIT_STATE_PATH")
    if raw and raw.strip():
        return Path(raw.strip())
    return DEFAULT_FMP_RATE_LIMIT_STATE_PATH


def _rate_limit_cooldown_sec() -> int:
    raw = os.getenv("FMP_RATE_LIMIT_COOLDOWN_SEC", "")
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = DEFAULT_FMP_RATE_LIMIT_COOLDOWN_SEC
    return max(5, parsed)


def _is_rate_limited_now() -> bool:
    path = _rate_limit_state_path()
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    try:
        blocked_until = float(payload.get("blocked_until_epoch", 0.0))
    except (TypeError, ValueError):
        blocked_until = 0.0
    return blocked_until > time.time()


def _mark_rate_limited_now() -> None:
    path = _rate_limit_state_path()
    now = time.time()
    payload = {
        "last_429_epoch": now,
        "blocked_until_epoch": now + float(_rate_limit_cooldown_sec()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
