from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from trading_skills_engine.config.env import ensure_project_env_loaded


class GLMClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class GLMClient:
    api_key: str
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4.5"
    timeout_sec: int = 90
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "GLMClient | None":
        ensure_project_env_loaded()
        api_key = str(os.getenv("GLM_API_KEY") or "").strip()
        if not api_key:
            return None
        base_url = str(os.getenv("GLM_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").strip()
        model = str(os.getenv("GLM_MODEL") or "glm-4.5").strip()
        timeout_raw = str(os.getenv("GLM_TIMEOUT_SEC") or "90").strip()
        retries_raw = str(os.getenv("GLM_MAX_RETRIES") or "2").strip()
        try:
            timeout_sec = max(15, min(180, int(timeout_raw)))
        except ValueError:
            timeout_sec = 90
        try:
            max_retries = max(0, min(4, int(retries_raw)))
        except ValueError:
            max_retries = 2
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_sec=timeout_sec,
            max_retries=max_retries,
        )

    def chat_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        parsed = self._post(payload)
        content = _extract_content(parsed)
        if not content:
            fallback_payload = {
                "model": self.model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            parsed = self._post(fallback_payload)
            content = _extract_content(parsed)
        if not content:
            raise GLMClientError("GLM_EMPTY_CONTENT")
        json_payload = _parse_json_content(content)
        if not isinstance(json_payload, dict):
            raise GLMClientError("GLM_CONTENT_NOT_JSON_OBJECT")
        return json_payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "trading-skills-engine/2.0",
            },
            method="POST",
        )
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(req, timeout=self.timeout_sec) as response:
                    raw = response.read().decode("utf-8")
                    parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise GLMClientError("GLM_RESPONSE_NOT_OBJECT")
                return parsed
            except TimeoutError as exc:
                if attempt < self.max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise GLMClientError("GLM_TIMEOUT") from exc
            except HTTPError as exc:
                if exc.code in {408, 429, 500, 502, 503, 504} and attempt < self.max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise GLMClientError(f"GLM_HTTP_{exc.code}") from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                raise GLMClientError("GLM_NETWORK_ERROR") from exc
            except json.JSONDecodeError as exc:
                raise GLMClientError("GLM_RESPONSE_NOT_JSON") from exc
            except GLMClientError:
                raise
            except Exception as exc:
                raise GLMClientError("GLM_RESPONSE_PARSE_ERROR") from exc
        raise GLMClientError("GLM_NETWORK_ERROR")


def _extract_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
                elif isinstance(item.get("content"), str):
                    chunks.append(str(item.get("content")).strip())
            return "\n".join(chunks).strip()
        if isinstance(content, dict):
            for key in ("text", "content", "output"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _parse_json_content(content: str) -> Any | None:
    text = content.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        maybe = text[start : end + 1]
        try:
            return json.loads(maybe)
        except Exception:
            return None
    return None
