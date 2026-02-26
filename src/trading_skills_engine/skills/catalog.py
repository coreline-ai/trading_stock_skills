from __future__ import annotations

from trading_skills_engine.core.models import SkillDefinition


SKILL_CATALOG: list[SkillDefinition] = [
    SkillDefinition("sector-analyst", "Sector Analyst", "market_analysis", "relative strength cycle", False, False),
    SkillDefinition("breadth-chart-analyst", "Breadth Chart Analyst", "market_analysis", "breadth phase model", False, False),
    SkillDefinition("technical-analyst", "Technical Analyst", "market_analysis", "trend and invalidation", False, False),
    SkillDefinition("market-news-analyst", "Market News Analyst", "market_analysis", "impact ranking", True, False),
    SkillDefinition("us-stock-analysis", "US Stock Analysis", "market_analysis", "fundamental+technical memo", True, True),
    SkillDefinition("market-environment-analysis", "Market Environment Analysis", "market_analysis", "cross-asset briefing", True, True),
    SkillDefinition("market-breadth-analyzer", "Market Breadth Analyzer", "market_analysis", "6-factor breadth score", False, False),
    SkillDefinition("uptrend-analyzer", "Uptrend Analyzer", "market_analysis", "uptrend participation", False, False),
    SkillDefinition("macro-regime-detector", "Macro Regime Detector", "market_analysis", "macro regime detection", False, True),
    SkillDefinition("institutional-flow-tracker", "Institutional Flow Tracker", "market_analysis", "13F smart money", False, True),
    SkillDefinition("theme-detector", "Theme Detector", "market_analysis", "theme heat and maturity", False, False),
    SkillDefinition("economic-calendar-fetcher", "Economic Calendar Fetcher", "calendar", "economic event impact", False, True),
    SkillDefinition("earnings-calendar", "Earnings Calendar", "calendar", "earnings schedule", False, True),
    SkillDefinition("scenario-analyzer", "Scenario Analyzer", "strategy_risk", "base-bull-bear scenarios", True, False),
    SkillDefinition("backtest-expert", "Backtest Expert", "strategy_risk", "robustness first", False, False),
    SkillDefinition("stanley-druckenmiller-investment", "Stanley Druckenmiller Investment", "strategy_risk", "macro conviction sizing", False, False),
    SkillDefinition("us-market-bubble-detector", "US Market Bubble Detector", "strategy_risk", "minsky bubble scale", False, False),
    SkillDefinition("options-strategy-advisor", "Options Strategy Advisor", "strategy_risk", "greeks and payoff", False, True),
    SkillDefinition("portfolio-manager", "Portfolio Manager", "strategy_risk", "allocation and rebalance", False, False),
    SkillDefinition("strategy-pivot-designer", "Strategy Pivot Designer", "strategy_risk", "stagnation pivot", False, False),
    SkillDefinition("market-top-detector", "Market Top Detector", "market_timing", "distribution days", False, True),
    SkillDefinition("ftd-detector", "FTD Detector", "market_timing", "follow-through day", False, True),
    SkillDefinition("earnings-trade-analyzer", "Earnings Trade Analyzer", "earnings_momentum", "post-earnings gap score", False, True),
    SkillDefinition("pead-screener", "PEAD Screener", "earnings_momentum", "post-earnings drift stages", False, True),
    SkillDefinition("vcp-screener", "VCP Screener", "screening", "minervini VCP", False, True),
    SkillDefinition("canslim-screener", "CANSLIM Screener", "screening", "o'neil 7-factor", False, True),
    SkillDefinition("value-dividend-screener", "Value Dividend Screener", "screening", "value income quality", False, True),
    SkillDefinition("dividend-growth-pullback-screener", "Dividend Growth Pullback Screener", "screening", "growth dividend pullback", False, True),
    SkillDefinition("kanchi-dividend-sop", "Kanchi Dividend SOP", "screening", "kanchi 5-step SOP", False, False),
    SkillDefinition("kanchi-dividend-review-monitor", "Kanchi Dividend Review Monitor", "screening", "review queue triggers", False, False),
    SkillDefinition("kanchi-dividend-us-tax-accounting", "Kanchi Dividend US Tax Accounting", "screening", "tax account location", False, False),
    SkillDefinition("pair-trade-screener", "Pair Trade Screener", "screening", "cointegration mean reversion", False, True),
    SkillDefinition("edge-candidate-agent", "Edge Candidate Agent", "edge_research", "ticket to strategy spec", False, False),
    SkillDefinition("edge-concept-synthesizer", "Edge Concept Synthesizer", "edge_research", "concept synthesis", True, False),
    SkillDefinition("edge-hint-extractor", "Edge Hint Extractor", "edge_research", "extract recurring edges", True, False),
    SkillDefinition("edge-strategy-designer", "Edge Strategy Designer", "edge_research", "strategy draft design", True, False),
    SkillDefinition("dual-axis-skill-reviewer", "Dual-Axis Skill Reviewer", "quality_orchestration", "deterministic+llm review", False, False),
    SkillDefinition("weekly-trade-strategy", "Weekly Trade Strategy", "quality_orchestration", "multi-skill chaining", True, False),
]


def skill_count() -> int:
    return len(SKILL_CATALOG)
