#!/usr/bin/env python3.11
from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from trading_skills_engine.engine.orchestrator_v2 import SkillEngineOrchestratorV2
from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.contracts import EngineRunRequestV2
from trading_skills_engine.skills_v2.traits import get_skill_trait


REPORT_DIR = ROOT_DIR / "reports" / "diagnostics"
JSON_PATH = REPORT_DIR / "latest_skill_uniqueness_report.json"
HTML_PATH = REPORT_DIR / "latest_skill_uniqueness_report.html"


@dataclass
class SkillRow:
    symbol: str
    score: float
    reason: str
    decision: str | None = None


def _recommender_symbols(
    orch: SkillEngineOrchestratorV2,
    result: Any,
    top_n: int = 8,
) -> list[SkillRow]:
    rows = orch._extract_ranked_symbols_for_recommender(result=result, top_n=top_n)
    return [SkillRow(symbol=symbol, score=round(score, 2), reason=reason) for symbol, score, reason in rows]


def _build_strength_map(rec_outputs: dict[str, list[SkillRow]], max_per_skill: int = 20) -> dict[str, float]:
    raw: dict[str, float] = {}
    for rows in rec_outputs.values():
        for row in rows[:max_per_skill]:
            raw[row.symbol] = raw.get(row.symbol, 0.0) + float(row.score)
    if not raw:
        return {}
    min_v = min(raw.values())
    max_v = max(raw.values())
    spread = max_v - min_v
    if spread <= 1e-9:
        return {symbol: 50.0 for symbol in raw}
    return {symbol: ((value - min_v) / spread) * 100.0 for symbol, value in raw.items()}


def _signature_rows(rows: list[SkillRow], include_decision: bool = False) -> tuple[Any, ...]:
    if include_decision:
        return tuple((row.symbol, round(row.score, 2), row.decision) for row in rows)
    return tuple((row.symbol, round(row.score, 2), row.reason) for row in rows)


def _render_html(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rec_outputs = report["recommender_outputs"]
    ana_outputs = report["analyzer_outputs"]
    rec_dup = report["recommender_duplicate_groups"]
    ana_dup = report["analyzer_duplicate_groups"]

    def _rows_to_table(rows: list[dict[str, Any]], include_decision: bool) -> str:
        if not rows:
            return "<p class='empty'>데이터 없음</p>"
        head = "<tr><th>symbol</th><th>score</th>"
        if include_decision:
            head += "<th>decision</th>"
        head += "<th>reason</th></tr>"
        body = []
        for row in rows:
            decision_cell = f"<td>{escape(str(row.get('decision') or '-'))}</td>" if include_decision else ""
            body.append(
                "<tr>"
                f"<td>{escape(str(row.get('symbol') or '-'))}</td>"
                f"<td>{escape(str(row.get('score') or '-'))}</td>"
                f"{decision_cell}"
                f"<td>{escape(str(row.get('reason') or '-'))}</td>"
                "</tr>"
            )
        return f"<table><thead>{head}</thead><tbody>{''.join(body)}</tbody></table>"

    rec_cards = []
    for slug, rows in rec_outputs.items():
        rec_cards.append(
            "<section class='card'>"
            f"<h3>{escape(slug)}</h3>"
            f"{_rows_to_table(rows, include_decision=False)}"
            "</section>"
        )

    ana_cards = []
    for slug, rows in ana_outputs.items():
        ana_cards.append(
            "<section class='card'>"
            f"<h3>{escape(slug)}</h3>"
            f"{_rows_to_table(rows, include_decision=True)}"
            "</section>"
        )

    def _dup_list(groups: list[list[str]]) -> str:
        if not groups:
            return "<li>없음</li>"
        return "".join(f"<li>{escape(', '.join(group))}</li>" for group in groups)

    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>Skill Uniqueness Report</title>
  <style>
    body {{ font-family: -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Arial,sans-serif; background:#f5f7fb; margin:0; padding:24px; color:#1b2430; }}
    .wrap {{ max-width:1400px; margin:0 auto; }}
    .summary {{ background:#fff; border:1px solid #d9e1ef; border-radius:12px; padding:16px; margin-bottom:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(440px,1fr)); gap:12px; }}
    .card {{ background:#fff; border:1px solid #d9e1ef; border-radius:12px; padding:12px; overflow:auto; }}
    h1 {{ margin:0 0 8px 0; font-size:20px; }}
    h2 {{ margin:20px 0 10px 0; font-size:16px; }}
    h3 {{ margin:0 0 10px 0; font-size:14px; }}
    table {{ width:100%; border-collapse:collapse; font-size:12px; }}
    th,td {{ border-bottom:1px solid #edf1f7; padding:6px; text-align:left; white-space:nowrap; }}
    th {{ background:#f8fbff; }}
    .ok {{ color:#1d7a3a; font-weight:700; }}
    .fail {{ color:#b42318; font-weight:700; }}
    .empty {{ color:#667085; }}
  </style>
</head>
<body>
<div class="wrap">
  <section class="summary">
    <h1>전체 스킬 자체 테스트 리포트</h1>
    <p>실행일: {escape(str(summary['as_of_date']))}</p>
    <p>추천 스킬 {summary['recommender_count']}개 / 분석 스킬 {summary['analyzer_count']}개</p>
    <p>추천 중복 그룹: <strong>{summary['recommender_duplicate_groups']}</strong>,
       분석 중복 그룹: <strong>{summary['analyzer_duplicate_groups']}</strong></p>
    <p>추천 누락: <strong>{summary['recommender_missing_count']}</strong>,
       분석 누락: <strong>{summary['analyzer_missing_count']}</strong></p>
    <p>최종 판정: <span class="{ 'ok' if summary['passed'] else 'fail' }">{'PASS' if summary['passed'] else 'FAIL'}</span></p>
    <h3>추천 중복 그룹</h3>
    <ul>{_dup_list(rec_dup)}</ul>
    <h3>분석 중복 그룹</h3>
    <ul>{_dup_list(ana_dup)}</ul>
  </section>
  <h2>추천 스킬별 결과</h2>
  <div class="grid">{''.join(rec_cards)}</div>
  <h2>분석 스킬별 결과</h2>
  <div class="grid">{''.join(ana_cards)}</div>
</div>
</body>
</html>
"""


def main() -> int:
    orch = SkillEngineOrchestratorV2()
    all_slugs = [item.slug for item in SKILL_CATALOG]
    response = orch.run(
        EngineRunRequestV2(
            selected_skills=all_slugs,
            as_of_date=date.today().isoformat(),
            top_picks_mode="skill_consensus",
        )
    )

    by_slug = {item.skill_slug: item for item in response.results if item.status == "ok"}
    recommender_slugs: list[str] = []
    analyzer_slugs: list[str] = []
    for slug in all_slugs:
        trait = get_skill_trait(slug)
        if trait is None or slug not in by_slug:
            continue
        if trait.recommendation_role in {"direct", "candidate"}:
            recommender_slugs.append(slug)
        else:
            analyzer_slugs.append(slug)

    recommender_outputs: dict[str, list[SkillRow]] = {}
    for slug in recommender_slugs:
        recommender_outputs[slug] = _recommender_symbols(orch=orch, result=by_slug[slug], top_n=8)

    symbol_pool: list[str] = []
    for rows in recommender_outputs.values():
        for row in rows:
            if row.symbol not in symbol_pool:
                symbol_pool.append(row.symbol)
    symbol_pool = symbol_pool[:20]

    symbol_strength = _build_strength_map(recommender_outputs, max_per_skill=20)
    analyzer_outputs: dict[str, list[SkillRow]] = {}
    for slug in analyzer_slugs:
        result = by_slug[slug]
        rows: list[SkillRow] = []
        for symbol in symbol_pool:
            evaluation = orch._evaluate_symbol_for_analyzer(
                symbol=symbol,
                result=result,
                target_group="top10",
                symbol_strength_0_100=symbol_strength.get(symbol),
            )
            rows.append(
                SkillRow(
                    symbol=symbol,
                    score=round(float(evaluation.score), 2),
                    decision=evaluation.decision,
                    reason=(" | ".join(evaluation.reasons[:3]) if evaluation.reasons else "-"),
                )
            )
        analyzer_outputs[slug] = rows

    recommender_sig: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for slug, rows in recommender_outputs.items():
        recommender_sig[_signature_rows(rows, include_decision=False)].append(slug)
    analyzer_sig: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for slug, rows in analyzer_outputs.items():
        analyzer_sig[_signature_rows(rows, include_decision=True)].append(slug)

    recommender_duplicate_groups = [sorted(group) for group in recommender_sig.values() if len(group) > 1]
    analyzer_duplicate_groups = [sorted(group) for group in analyzer_sig.values() if len(group) > 1]
    recommender_missing = [slug for slug, rows in recommender_outputs.items() if not rows]
    analyzer_missing = [slug for slug, rows in analyzer_outputs.items() if not rows]

    passed = not recommender_duplicate_groups and not analyzer_duplicate_groups and not recommender_missing and not analyzer_missing
    report: dict[str, Any] = {
        "summary": {
            "as_of_date": response.as_of_date,
            "recommender_count": len(recommender_slugs),
            "analyzer_count": len(analyzer_slugs),
            "recommender_duplicate_groups": len(recommender_duplicate_groups),
            "analyzer_duplicate_groups": len(analyzer_duplicate_groups),
            "recommender_missing_count": len(recommender_missing),
            "analyzer_missing_count": len(analyzer_missing),
            "passed": passed,
        },
        "recommender_duplicate_groups": recommender_duplicate_groups,
        "analyzer_duplicate_groups": analyzer_duplicate_groups,
        "recommender_missing": recommender_missing,
        "analyzer_missing": analyzer_missing,
        "recommender_outputs": {
            slug: [asdict(row) for row in rows]
            for slug, rows in recommender_outputs.items()
        },
        "analyzer_outputs": {
            slug: [asdict(row) for row in rows]
            for slug, rows in analyzer_outputs.items()
        },
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    HTML_PATH.write_text(_render_html(report), encoding="utf-8")

    print(f"report_json={JSON_PATH}")
    print(f"report_html={HTML_PATH}")
    print(f"passed={passed}")
    print(f"recommender_duplicate_groups={len(recommender_duplicate_groups)}")
    print(f"analyzer_duplicate_groups={len(analyzer_duplicate_groups)}")
    print(f"recommender_missing={len(recommender_missing)}")
    print(f"analyzer_missing={len(analyzer_missing)}")
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
