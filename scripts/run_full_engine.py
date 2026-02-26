#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trading_skills_engine.engine.orchestrator import SkillEngineOrchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all trading skills and build dashboard artifacts")
    parser.add_argument(
        "--output",
        default="reports/skill_runs/latest_skill_runs.json",
        help="Full skill run report path",
    )
    parser.add_argument(
        "--snapshot-output",
        default="reports/eod/latest_snapshot.json",
        help="Dashboard snapshot output path",
    )
    parser.add_argument(
        "--skills",
        default="",
        help="Comma-separated skill slugs to run (default: all 38)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    orchestrator = SkillEngineOrchestrator()
    selected = [item.strip() for item in args.skills.split(",") if item.strip()]
    report = orchestrator.write_report(Path(args.output), selected_slugs=selected or None)

    snapshot = {
        "app_name": report["app_name"],
        "as_of_date": report["as_of_date"],
        "notification_count": report["notification_count"],
        "auto_rebalance_enabled": report["auto_rebalance_enabled"],
        "strategy_profiles": report["strategy_profiles"],
        "skill_classification_counts": report["skill_classification_counts"],
        "top_picks": report["top_picks"],
    }

    snapshot_path = Path(args.snapshot_output)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Generated {report['skill_count']} skills")
    print(f"Report: {args.output}")
    print(f"Snapshot: {args.snapshot_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
