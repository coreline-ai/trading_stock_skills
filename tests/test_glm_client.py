from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from trading_skills_engine.ai.glm_client import GLMClient, GLMClientError


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


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

    monkeypatch.setattr(
        "trading_skills_engine.ai.glm_client.urlopen",
        lambda req, timeout=20: _FakeResponse(payload),  # noqa: ARG005
    )
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
    monkeypatch.setattr(
        "trading_skills_engine.ai.glm_client.urlopen",
        lambda req, timeout=20: _FakeResponse(payload),  # noqa: ARG005
    )
    client = GLMClient(api_key="test-key")
    with pytest.raises(GLMClientError):
        client.chat_json(system_prompt="sys", user_prompt="user")


def test_glm_chat_json_raises_on_http_error(monkeypatch):
    def _raise(*args, **kwargs):  # noqa: ANN002, ANN003
        raise HTTPError("https://example.com", 401, "unauthorized", hdrs=None, fp=None)

    monkeypatch.setattr("trading_skills_engine.ai.glm_client.urlopen", _raise)
    client = GLMClient(api_key="test-key")
    with pytest.raises(GLMClientError) as exc:
        client.chat_json(system_prompt="sys", user_prompt="user")
    assert "GLM_HTTP_401" in str(exc.value)

