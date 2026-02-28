#!/usr/bin/env python3.11
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
from html import escape
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2, SkillRunResultV2


REPORT_DIR = ROOT_DIR / "reports" / "diagnostics"
JSON_PATH = REPORT_DIR / "latest_skill_independence_report.json"
HTML_PATH = REPORT_DIR / "latest_skill_independence_report.html"


@dataclass
class SkillCheckRow:
    slug: str
    display_name: str
    passed: bool
    status_all: str
    status_single: str
    score_all: float | None
    score_single: float | None
    confidence_all: float | None
    confidence_single: float | None
    payload_hash_all: str
    payload_hash_single: str
    differences: list[str]


def _fixed_rss_fetch(*, max_items: int = 80) -> tuple[list[dict[str, Any]], list[str]]:
    del max_items
    return (
        [
            {
                "headline": "NVDA and AVGO lead AI momentum while Fed remains data dependent",
                "source": "Deterministic RSS",
                "source_url": "https://example.com/deterministic-rss",
                "published_at": "2026-02-28T00:00:00+00:00",
            }
        ],
        [],
    )


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False, sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _index_by_slug(results: list[SkillRunResultV2]) -> dict[str, SkillRunResultV2]:
    return {item.skill_slug: item for item in results}


def _normalize_score(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _normalize_conf(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _compare(all_item: SkillRunResultV2, single_item: SkillRunResultV2) -> SkillCheckRow:
    differences: list[str] = []
    if all_item.status != single_item.status:
        differences.append(f"status:{all_item.status}->{single_item.status}")
    if _normalize_score(all_item.score_0_100) != _normalize_score(single_item.score_0_100):
        differences.append(f"score:{all_item.score_0_100}->{single_item.score_0_100}")
    if _normalize_conf(all_item.confidence_0_1) != _normalize_conf(single_item.confidence_0_1):
        differences.append(f"confidence:{all_item.confidence_0_1}->{single_item.confidence_0_1}")
    if (all_item.reason_code or "") != (single_item.reason_code or ""):
        differences.append(f"reason_code:{all_item.reason_code}->{single_item.reason_code}")

    hash_all = _payload_hash(all_item.analysis_payload)
    hash_single = _payload_hash(single_item.analysis_payload)
    if hash_all != hash_single:
        differences.append("analysis_payload_hash_mismatch")

    if dict(all_item.source_statuses or {}) != dict(single_item.source_statuses or {}):
        differences.append("source_statuses_mismatch")

    definition = next((item for item in SKILL_CATALOG if item.slug == all_item.skill_slug), None)
    display_name = definition.display_name if definition else all_item.skill_slug
    return SkillCheckRow(
        slug=all_item.skill_slug,
        display_name=display_name,
        passed=(len(differences) == 0),
        status_all=all_item.status,
        status_single=single_item.status,
        score_all=_normalize_score(all_item.score_0_100),
        score_single=_normalize_score(single_item.score_0_100),
        confidence_all=_normalize_conf(all_item.confidence_0_1),
        confidence_single=_normalize_conf(single_item.confidence_0_1),
        payload_hash_all=hash_all,
        payload_hash_single=hash_single,
        differences=differences,
    )


def _render_html(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = report["rows"]
    body_rows: list[str] = []
    for row in rows:
        diffs = row["differences"]
        diff_text = ", ".join(diffs) if diffs else "-"
        status_cls = "ok" if row["passed"] else "fail"
        body_rows.append(
            "<tr>"
            f"<td>{escape(row['slug'])}</td>"
            f"<td>{escape(row['display_name'])}</td>"
            f"<td class='{status_cls}'>{'PASS' if row['passed'] else 'FAIL'}</td>"
            f"<td>{escape(str(row['status_all']))}</td>"
            f"<td>{escape(str(row['status_single']))}</td>"
            f"<td>{escape(str(row['score_all']))}</td>"
            f"<td>{escape(str(row['score_single']))}</td>"
            f"<td>{escape(str(row['confidence_all']))}</td>"
            f"<td>{escape(str(row['confidence_single']))}</td>"
            f"<td>{escape(diff_text)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Skill Independence Report</title>
  <style>
    body {{ font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif; background:#f5f7fb; margin:0; padding:24px; color:#1b2430; }}
    .wrap {{ max-width:1500px; margin:0 auto; }}
    .summary {{ background:#fff; border:1px solid #d9e1ef; border-radius:12px; padding:16px; margin-bottom:16px; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid #d9e1ef; border-radius:12px; overflow:hidden; }}
    th, td {{ border-bottom:1px solid #edf1f7; padding:6px 8px; text-align:left; font-size:12px; }}
    th {{ background:#f8fbff; }}
    .ok {{ color:#1d7a3a; font-weight:700; }}
    .fail {{ color:#b42318; font-weight:700; }}
  </style>
</head>
<body>
<div class="wrap">
  <section class="summary">
    <h1>스킬 독립성 점검 리포트</h1>
    <p>실행일: {escape(summary['as_of_date'])}</p>
    <p>총 {summary['total_skills']}개 스킬 중 PASS {summary['passed_count']} / FAIL {summary['failed_count']}</p>
    <p>최종 판정: <span class="{'ok' if summary['passed'] else 'fail'}">{'PASS' if summary['passed'] else 'FAIL'}</span></p>
  </section>
  <table>
    <thead>
      <tr>
        <th>slug</th>
        <th>display_name</th>
        <th>result</th>
        <th>status(all)</th>
        <th>status(single)</th>
        <th>score(all)</th>
        <th>score(single)</th>
        <th>confidence(all)</th>
        <th>confidence(single)</th>
        <th>differences</th>
      </tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def main() -> int:
    all_slugs = [item.slug for item in SKILL_CATALOG]
    as_of = date(2026, 2, 28)

    orchestrator = SkillEngineOrchestratorV2()
    # Deterministic mode: disable live sources and pin RSS payload.
    orchestrator.market_provider.client = None
    orchestrator.fmp_calendar = None
    orchestrator.fmp_news = None
    orchestrator.rss_client.fetch = _fixed_rss_fetch  # type: ignore[assignment]

    all_run = orchestrator.run(
        EngineRunRequestV2(
            selected_skills=all_slugs,
            as_of_date=as_of,
            top_picks_mode="skill_consensus",
        )
    )
    all_by_slug = _index_by_slug(all_run.results)

    rows: list[SkillCheckRow] = []
    for slug in all_slugs:
        single_run = orchestrator.run(
            EngineRunRequestV2(
                selected_skills=[slug],
                as_of_date=as_of,
                top_picks_mode="skill_consensus",
            )
        )
        single_by_slug = _index_by_slug(single_run.results)
        if slug not in all_by_slug or slug not in single_by_slug:
            definition = next((item for item in SKILL_CATALOG if item.slug == slug), None)
            rows.append(
                SkillCheckRow(
                    slug=slug,
                    display_name=(definition.display_name if definition else slug),
                    passed=False,
                    status_all=all_by_slug.get(slug).status if slug in all_by_slug else "missing",
                    status_single=single_by_slug.get(slug).status if slug in single_by_slug else "missing",
                    score_all=None,
                    score_single=None,
                    confidence_all=None,
                    confidence_single=None,
                    payload_hash_all="",
                    payload_hash_single="",
                    differences=["missing_result_row"],
                )
            )
            continue
        rows.append(_compare(all_by_slug[slug], single_by_slug[slug]))

    passed_count = sum(1 for row in rows if row.passed)
    failed_count = len(rows) - passed_count
    summary = {
        "as_of_date": as_of.isoformat(),
        "total_skills": len(rows),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "passed": failed_count == 0,
    }
    report = {
        "summary": summary,
        "rows": [asdict(row) for row in rows],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    HTML_PATH.write_text(_render_html(report), encoding="utf-8")

    print(f"report_json={JSON_PATH}")
    print(f"report_html={HTML_PATH}")
    print(f"passed={summary['passed']}")
    print(f"failed_count={summary['failed_count']}")
    return 0 if summary["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
