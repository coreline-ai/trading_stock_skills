from __future__ import annotations

from trading_skills_engine.ai.zai_search_mcp_client import (
    _extract_evidence_from_call_obj,
    _parse_search_rows,
    _parse_sse_jsonrpc,
)


def test_parse_sse_jsonrpc_reads_data_block():
    body = (
        "id:1\n"
        "event:message\n"
        'data:{"jsonrpc":"2.0","id":"x","result":{"ok":true}}\n\n'
    )
    parsed = _parse_sse_jsonrpc(body)
    assert parsed is not None
    assert parsed["result"]["ok"] is True


def test_parse_search_rows_handles_double_encoded_json():
    text = (
        '"[{\\\"title\\\":\\\"AAPL news\\\",\\\"link\\\":\\\"https://example.com/aapl\\\",'
        '\\\"content\\\":\\\"summary\\\",\\\"publish_date\\\":\\\"2026-03-01\\\"}]"'
    )
    rows = _parse_search_rows(text)
    assert len(rows) == 1
    assert rows[0]["title"] == "AAPL news"


def test_extract_evidence_from_call_obj_maps_metrics():
    call_obj = {
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        '"[{\\\"title\\\":\\\"NVDA update\\\",\\\"link\\\":\\\"https://example.com/nvda\\\",'
                        '\\\"content\\\":\\\"earnings beat\\\",\\\"publish_date\\\":\\\"2026-03-01\\\",'
                        '\\\"media\\\":\\\"Example\\\"}]"'
                    ),
                }
            ],
            "isError": False,
        }
    }
    evidence = _extract_evidence_from_call_obj(call_obj, max_results=2)
    assert len(evidence) == 1
    assert evidence[0]["source"] == "zai_search_mcp"
    assert evidence[0]["url"] == "https://example.com/nvda"
    assert evidence[0]["metrics"]["title"] == "NVDA update"
