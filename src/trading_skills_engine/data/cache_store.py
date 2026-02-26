from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CacheEntry:
    payload: Any
    fetched_at: datetime
    expires_at: datetime


class CacheStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path("reports/cache/v2")
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def set(self, key: str, payload: Any, ttl_hours: int) -> CacheEntry:
        now = datetime.now(UTC)
        expires = now + timedelta(hours=ttl_hours)
        entry = {
            "payload": payload,
            "fetched_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
        self._path_for_key(key).write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        return CacheEntry(payload=payload, fetched_at=now, expires_at=expires)

    def get(self, key: str) -> CacheEntry | None:
        path = self._path_for_key(key)
        if not path.exists():
            return None

        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(obj["fetched_at"])
            expires_at = datetime.fromisoformat(obj["expires_at"])
            payload = obj["payload"]
            return CacheEntry(payload=payload, fetched_at=fetched_at, expires_at=expires_at)
        except Exception:
            return None

    def get_fresh(self, key: str) -> CacheEntry | None:
        entry = self.get(key)
        if not entry:
            return None
        if datetime.now(UTC) <= entry.expires_at:
            return entry
        return None

    def get_stale(self, key: str) -> CacheEntry | None:
        return self.get(key)

    @staticmethod
    def cache_info(mode: str, entry: CacheEntry | None) -> dict[str, str | None]:
        if not entry:
            return {"mode": mode, "fetched_at": None, "expires_at": None}
        return {
            "mode": mode,
            "fetched_at": entry.fetched_at.isoformat(),
            "expires_at": entry.expires_at.isoformat(),
        }

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.base_dir / f"{digest}.json"
