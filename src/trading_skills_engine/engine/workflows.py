from __future__ import annotations

from trading_skills_engine.core.models import SkillRunResult, WorkflowResult


WORKFLOW_MAP: dict[str, list[str]] = {
    "daily_market_monitoring": [
        "economic-calendar-fetcher",
        "earnings-calendar",
        "market-news-analyst",
        "breadth-chart-analyst",
        "uptrend-analyzer",
    ],
    "macro_positioning": [
        "macro-regime-detector",
        "market-top-detector",
        "ftd-detector",
        "scenario-analyzer",
        "stanley-druckenmiller-investment",
    ],
    "stock_research": [
        "us-stock-analysis",
        "earnings-trade-analyzer",
        "market-news-analyst",
        "backtest-expert",
    ],
}


def build_workflow_results(skill_results: list[SkillRunResult]) -> list[WorkflowResult]:
    by_slug = {item.skill_slug: item for item in skill_results}
    workflows: list[WorkflowResult] = []

    for workflow_name, slugs in WORKFLOW_MAP.items():
        picked = [by_slug[slug] for slug in slugs if slug in by_slug]
        if not picked:
            continue

        avg_score = sum(item.score_0_100 for item in picked) / len(picked)
        if avg_score >= 63:
            exposure = "70-100%"
            bias = "Risk-On"
        elif avg_score >= 48:
            exposure = "40-70%"
            bias = "Balanced"
        else:
            exposure = "10-40%"
            bias = "Risk-Off"

        actions = [
            f"{picked[0].skill_slug} 신호 재검증",
            f"상위 후보 {', '.join(picked[0].top_candidates[:3])} 우선 모니터링",
        ]

        workflows.append(
            WorkflowResult(
                workflow_name=workflow_name,
                exposure_band=exposure,
                portfolio_bias=bias,
                top_actions=actions,
                contributing_skills=[item.skill_slug for item in picked],
            )
        )

    return workflows
