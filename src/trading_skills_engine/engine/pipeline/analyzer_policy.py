from __future__ import annotations

from typing import Any


def accepted_decisions_for_policy(policy: str) -> set[str]:
    return {"PASS"} if str(policy).strip().lower() == "all_pass" else {"PASS", "WATCH"}


def filter_symbols_by_policy(
    symbols: list[str],
    analyzer_skills: list[str],
    analyzer_decisions_by_skill: dict[str, dict[str, str]],
    analyzer_pass_policy: str,
) -> list[str]:
    if not symbols or not analyzer_skills:
        return []

    accepted = accepted_decisions_for_policy(analyzer_pass_policy)
    filtered = set(symbols)
    for analyzer_slug in analyzer_skills:
        decision_map = analyzer_decisions_by_skill.get(analyzer_slug, {})
        accepted_symbols = {symbol for symbol in symbols if decision_map.get(symbol) in accepted}
        filtered &= accepted_symbols
    return sorted(filtered)


def apply_policy_by_recommender(
    symbols_by_recommender: dict[str, list[str]],
    analyzer_skills: list[str],
    analyzer_decisions_by_skill: dict[str, dict[str, dict[str, str]]],
    analyzer_pass_policy: str,
    recommender_order: list[str],
) -> tuple[dict[str, set[str]], list[str]]:
    accepted = accepted_decisions_for_policy(analyzer_pass_policy)
    filtered_sets: dict[str, set[str]] = {}
    for recommender_slug, symbols in symbols_by_recommender.items():
        filtered = set(symbols)
        for analyzer_slug in analyzer_skills:
            decision_map = analyzer_decisions_by_skill.get(analyzer_slug, {}).get(recommender_slug, {})
            accepted_symbols = {symbol for symbol in symbols if decision_map.get(symbol) in accepted}
            filtered &= accepted_symbols
        filtered_sets[recommender_slug] = filtered

    if len(recommender_order) >= 2:
        intersection_set = set(filtered_sets.get(recommender_order[0], set()))
        for slug in recommender_order[1:]:
            intersection_set &= set(filtered_sets.get(slug, set()))
        final_symbols = sorted(intersection_set)
    elif len(recommender_order) == 1:
        final_symbols = sorted(filtered_sets.get(recommender_order[0], set()))
    else:
        final_symbols = []
    return filtered_sets, final_symbols


def build_post_analyzer_rows(
    filtered_sets_by_recommender: dict[str, set[str]],
    final_symbols: list[str],
    recommender_order: list[str],
) -> list[dict[str, Any]]:
    final_set = set(final_symbols)
    rows: list[dict[str, Any]] = []
    for recommender_slug in recommender_order:
        filtered = sorted(symbol for symbol in filtered_sets_by_recommender.get(recommender_slug, set()) if symbol in final_set)
        rows.append(
            {
                "recommender_skill": recommender_slug,
                "symbols": filtered,
                "count": len(filtered),
            }
        )
    return rows

