from __future__ import annotations

import os
from pathlib import Path


def ensure_project_env_loaded() -> None:
    if _is_truthy(os.getenv("TRADING_SKILLS_DISABLE_DOTENV", "")):
        return

    raw_path = os.getenv("TRADING_SKILLS_ENV_FILE", "").strip()
    if raw_path:
        env_path = Path(raw_path).expanduser()
    else:
        env_path = Path(__file__).resolve().parents[3] / ".env"
    load_env_file(env_path)


def load_env_file(path: Path, override: bool = False) -> None:
    if not path.exists() or not path.is_file():
        return

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return

    for line in lines:
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        if override or key not in os.environ:
            os.environ[key] = value


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None

    if text.startswith("export "):
        text = text[len("export ") :].strip()

    if "=" not in text:
        return None

    key, raw_value = text.split("=", 1)
    key = key.strip()
    value = raw_value.strip()
    if not key:
        return None

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    else:
        value = value.split(" #", 1)[0].strip()

    return key, value


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "on", "yes"}
