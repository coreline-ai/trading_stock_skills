from __future__ import annotations

import re
from typing import Any

_SYMBOL_RE = re.compile(r"[A-Z0-9.\-]+")
_SLUG_RE = re.compile(r"[a-z0-9\-]+")


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def parse_symbol_list(
    value: Any,
    *,
    max_items: int = 200,
    max_len: int = 10,
) -> list[str]:
    if isinstance(value, str):
        tokens = re.split(r"[\s,]+", value)
    elif isinstance(value, list):
        tokens = [str(item) for item in value]
    else:
        tokens = []

    parsed: list[str] = []
    for token in tokens[: max_items * 2]:
        symbol = str(token).strip().upper()
        if not symbol or symbol in parsed:
            continue
        if len(symbol) > max_len:
            continue
        if _SYMBOL_RE.fullmatch(symbol) is None:
            continue
        parsed.append(symbol)
        if len(parsed) >= max_items:
            break
    return parsed


def parse_slug_list(
    value: Any,
    *,
    max_items: int = 100,
    max_len: int = 80,
) -> list[str]:
    if isinstance(value, str):
        tokens = re.split(r"[\s,]+", value)
    elif isinstance(value, list):
        tokens = [str(item) for item in value]
    else:
        tokens = []

    parsed: list[str] = []
    for token in tokens[: max_items * 2]:
        slug = str(token).strip().lower()
        if not slug or slug in parsed:
            continue
        if len(slug) > max_len:
            continue
        if _SLUG_RE.fullmatch(slug) is None:
            continue
        parsed.append(slug)
        if len(parsed) >= max_items:
            break
    return parsed

