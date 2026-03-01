from __future__ import annotations

import json

import httpx
import pytest

from trading_skills_engine.ai.glm_client import GLMClient, GLMClientError


def _response(status_code: int, payload: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    return httpx.Response(status_code=status_code, json=payload, request=request)


def test_glm_chat_json_parses_valid_content(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "portfolio_summary_ko": "ok",
                            "symbols": [{"symbol": "NVDA", "decision": "BUY"}],
                        },
                        ensure_ascii=False,
                    )
                }
            }
        ]
    }

    monkeypatch.setattr(httpx.Client, "post", lambda self, url, json: _response(200, payload))  # noqa: ARG005
    client = GLMClient(api_key="test-key")
    result = client.chat_json(system_prompt="sys", user_prompt="user")
    assert result["portfolio_summary_ko"] == "ok"
    assert result["symbols"][0]["symbol"] == "NVDA"


def test_glm_chat_json_raises_on_malformed_content(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": "not a json response"
                }
            }
        ]
    }
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, json: _response(200, payload))  # noqa: ARG005
    client = GLMClient(api_key="test-key")
    with pytest.raises(GLMClientError):
        client.chat_json(system_prompt="sys", user_prompt="user")


def test_glm_chat_json_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(httpx.Client, "post", lambda self, url, json: _response(401, {"error": "unauthorized"}))  # noqa: ARG005
    client = GLMClient(api_key="test-key")
    with pytest.raises(GLMClientError) as exc:
        client.chat_json(system_prompt="sys", user_prompt="user")
    assert "GLM_HTTP_401" in str(exc.value)


def test_glm_chat_json_retries_on_timeout_then_succeeds(monkeypatch):
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"portfolio_summary_ko": "ok", "symbols": []}, ensure_ascii=False)
                }
            }
        ]
    }
    calls = {"count": 0}

    def _flaky(self, url, json):  # noqa: ANN001, ARG001
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("slow")
        return _response(200, payload)

    monkeypatch.setattr(httpx.Client, "post", _flaky)
    monkeypatch.setattr("trading_skills_engine.ai.glm_client.time.sleep", lambda sec: None)  # noqa: ARG005

    client = GLMClient(api_key="test-key", timeout_sec=30, max_retries=1)
    result = client.chat_json(system_prompt="sys", user_prompt="user")
    assert result["portfolio_summary_ko"] == "ok"
    assert calls["count"] == 2


def test_glm_from_env_uses_expanded_defaults(monkeypatch):
    monkeypatch.setenv("TRADING_SKILLS_DISABLE_DOTENV", "1")
    monkeypatch.setenv("GLM_API_KEY", "key")
    monkeypatch.delenv("GLM_TIMEOUT_SEC", raising=False)
    monkeypatch.delenv("GLM_MAX_RETRIES", raising=False)

    client = GLMClient.from_env()
    assert client is not None
    assert client.timeout_sec == 90
    assert client.max_retries == 2
