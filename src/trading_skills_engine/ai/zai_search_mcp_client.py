from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from trading_skills_engine.config.env import ensure_project_env_loaded

DEFAULT_ZAI_SEARCH_MCP_URL = "https://api.z.ai/api/mcp/web_search_prime/mcp"


class ZAISearchMCPError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZAISearchMCPClient:
    api_key: str
    endpoint: str = DEFAULT_ZAI_SEARCH_MCP_URL
    timeout_sec: int = 20
    max_results: int = 2
    recency: str = "oneWeek"
    content_size: str = "medium"
    location: str = "us"

    @classmethod
    def from_env(cls) -> "ZAISearchMCPClient | None":
        ensure_project_env_loaded()
        enabled = _to_bool(os.getenv("ZAI_SEARCH_MCP_ENABLED"), default=True)
        if not enabled:
            return None

        raw_key = str(os.getenv("ZAI_SEARCH_MCP_API_KEY") or os.getenv("GLM_API_KEY") or "").strip()
        if not raw_key:
            return None

        endpoint = str(os.getenv("ZAI_SEARCH_MCP_URL") or DEFAULT_ZAI_SEARCH_MCP_URL).strip()
        timeout_sec = _to_int(os.getenv("ZAI_SEARCH_MCP_TIMEOUT_SEC"), default=20, lo=5, hi=60)
        max_results = _to_int(os.getenv("ZAI_SEARCH_MCP_MAX_RESULTS"), default=2, lo=1, hi=5)
        recency = str(os.getenv("ZAI_SEARCH_MCP_RECENCY") or "oneWeek").strip() or "oneWeek"
        content_size = str(os.getenv("ZAI_SEARCH_MCP_CONTENT_SIZE") or "medium").strip() or "medium"
        location = str(os.getenv("ZAI_SEARCH_MCP_LOCATION") or "us").strip() or "us"
        return cls(
            api_key=raw_key,
            endpoint=endpoint,
            timeout_sec=timeout_sec,
            max_results=max_results,
            recency=recency,
            content_size=content_size,
            location=location,
        )

    def search_symbol_evidence(self, symbol: str) -> list[dict[str, Any]]:
        query = f"{str(symbol).upper()} stock latest news and earnings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "trading-skills-engine/2.0",
        }
        timeout = httpx.Timeout(float(self.timeout_sec))

        with httpx.Client(timeout=timeout, headers=headers) as client:
            session_id, _ = self._rpc(
                client=client,
                payload={
                    "jsonrpc": "2.0",
                    "id": "init-1",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "trading-skills-dashboard", "version": "0.1.0"},
                    },
                },
                session_id=None,
            )
            _, call_obj = self._rpc(
                client=client,
                payload={
                    "jsonrpc": "2.0",
                    "id": "call-1",
                    "method": "tools/call",
                    "params": {
                        "name": "webSearchPrime",
                        "arguments": {
                            "search_query": query,
                            "search_recency_filter": self.recency,
                            "content_size": self.content_size,
                            "location": self.location,
                        },
                    },
                },
                session_id=session_id,
            )

        return _extract_evidence_from_call_obj(call_obj, max_results=self.max_results)

    def _rpc(
        self,
        client: httpx.Client,
        payload: dict[str, Any],
        session_id: str | None,
    ) -> tuple[str | None, dict[str, Any]]:
        extra_headers: dict[str, str] = {}
        if session_id:
            extra_headers["mcp-session-id"] = session_id

        response = client.post(self.endpoint, json=payload, headers=extra_headers)
        if response.status_code >= 400:
            raise ZAISearchMCPError(f"ZAI_SEARCH_HTTP_{response.status_code}")

        next_session_id = response.headers.get("mcp-session-id") or session_id
        obj = _parse_sse_jsonrpc(response.text)
        if not isinstance(obj, dict):
            raise ZAISearchMCPError("ZAI_SEARCH_BAD_SSE_PAYLOAD")

        if isinstance(obj.get("error"), dict):
            message = str(obj["error"].get("message") or "ZAI_SEARCH_RPC_ERROR")
            raise ZAISearchMCPError(f"ZAI_SEARCH_RPC_ERROR:{message}")

        result = obj.get("result")
        if isinstance(result, dict) and bool(result.get("isError")):
            content = result.get("content")
            if isinstance(content, list) and content and isinstance(content[0], dict):
                message = str(content[0].get("text") or "ZAI_SEARCH_TOOL_ERROR")
            else:
                message = "ZAI_SEARCH_TOOL_ERROR"
            raise ZAISearchMCPError(message)

        return next_session_id, obj


def _extract_evidence_from_call_obj(call_obj: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
    result = call_obj.get("result")
    if not isinstance(result, dict):
        return []
    content = result.get("content")
    if not isinstance(content, list):
        return []
    text_chunks = [str(item.get("text") or "") for item in content if isinstance(item, dict)]
    merged_text = "\n".join([chunk for chunk in text_chunks if chunk.strip()]).strip()
    if not merged_text:
        return []

    rows = _parse_search_rows(merged_text)
    evidence: list[dict[str, Any]] = []
    for row in rows[:max_results]:
        if not isinstance(row, dict):
            continue
        url = str(row.get("link") or row.get("url") or "").strip()
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("content") or row.get("summary") or "").strip()
        publish_date = str(row.get("publish_date") or row.get("date") or "").strip()
        media = str(row.get("media") or row.get("site") or "").strip()
        evidence.append(
            {
                "source": "zai_search_mcp",
                "url": url,
                "metrics": {
                    "title": title[:180],
                    "snippet": snippet[:260],
                    "publish_date": publish_date[:40],
                    "media": media[:80],
                },
            }
        )
    return evidence


def _parse_sse_jsonrpc(body: str) -> dict[str, Any] | None:
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        data_lines.append(payload)
    if not data_lines:
        return None
    try:
        parsed = json.loads(data_lines[-1])
    except Exception:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_search_rows(text: str) -> list[dict[str, Any]]:
    parsed_once = _json_load_maybe(text)
    if isinstance(parsed_once, list):
        return [item for item in parsed_once if isinstance(item, dict)]

    if isinstance(parsed_once, str):
        parsed_twice = _json_load_maybe(parsed_once)
        if isinstance(parsed_twice, list):
            return [item for item in parsed_twice if isinstance(item, dict)]

    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        maybe = text[start : end + 1]
        parsed = _json_load_maybe(maybe)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _json_load_maybe(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _to_int(value: str | None, default: int, *, lo: int, hi: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, parsed))


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
