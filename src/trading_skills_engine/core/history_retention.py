from __future__ import annotations

import logging
import time
from pathlib import Path


def prune_history_files(
    history_dir: Path,
    *,
    max_files: int = 0,
    max_age_days: int = 0,
    pattern: str = "*.json",
    logger: logging.Logger | None = None,
) -> None:
    if not history_dir.exists() or not history_dir.is_dir():
        return

    files = [path for path in history_dir.glob(pattern) if path.is_file()]
    if not files:
        return

    if max_age_days > 0:
        cutoff_epoch = time.time() - (max_age_days * 86_400)
        for path in list(files):
            try:
                if path.stat().st_mtime < cutoff_epoch:
                    path.unlink(missing_ok=True)
            except Exception:
                if logger is not None:
                    logger.warning("history retention delete failed path=%s", path, exc_info=True)
        files = [path for path in history_dir.glob(pattern) if path.is_file()]

    if max_files > 0 and len(files) > max_files:
        try:
            files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        except Exception:
            # Fall back to lexical order when stat metadata is unavailable.
            files.sort(reverse=True)
        for path in files[max_files:]:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                if logger is not None:
                    logger.warning("history retention prune failed path=%s", path, exc_info=True)

