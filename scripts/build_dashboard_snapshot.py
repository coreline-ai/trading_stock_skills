#!/usr/bin/env python3
"""Build dashboard snapshot from latest skill run aggregate.

This script is intended to run at end of EOD batch and write
reports/eod/latest_snapshot.json consumed by the dashboard BFF.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dashboard snapshot for UI")
    parser.add_argument(
        "--source",
        default="reports/skill_runs/latest_skill_runs.json",
        help="Path to aggregated skill run JSON",
    )
    parser.add_argument(
        "--output",
        default="reports/eod/latest_snapshot.json",
        help="Output snapshot path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = Path(args.source)
    output_path = Path(args.output)

    if not source_path.exists():
        raise FileNotFoundError(
            f"Skill run aggregate not found: {source_path}. "
            "Run EOD skill workflow before snapshot generation."
        )

    source = json.loads(source_path.read_text(encoding="utf-8"))

    snapshot = {
        "app_name": source.get("app_name", "Coreline Stock AI"),
        "as_of_date": source.get("as_of_date", date.today().isoformat()),
        "notification_count": source.get("notification_count", 0),
        "user_avatar_url": source.get("user_avatar_url", ""),
        "auto_rebalance_enabled": source.get("auto_rebalance_enabled", True),
        "strategy_profiles": source.get("strategy_profiles", {}),
        "skill_classification_counts": source.get("skill_classification_counts", {}),
        "top_picks": source.get("top_picks", []),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote snapshot: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
