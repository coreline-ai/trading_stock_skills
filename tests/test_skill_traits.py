from __future__ import annotations

from trading_skills_engine.skills.catalog import SKILL_CATALOG
from trading_skills_engine.skills_v2.registry import is_recommendation_capable
from trading_skills_engine.skills_v2.traits import all_skill_traits, get_skill_trait


def test_all_catalog_skills_have_traits():
    traits = all_skill_traits()
    assert len(traits) == len(SKILL_CATALOG) == 38

    for skill in SKILL_CATALOG:
        trait = get_skill_trait(skill.slug)
        assert trait is not None
        assert trait.style
        assert trait.axis_weights
        assert abs(sum(trait.axis_weights.values()) - 1.0) < 0.01


def test_recommendation_capability_is_trait_driven():
    assert is_recommendation_capable("us-stock-analysis") is True
    assert is_recommendation_capable("market-news-analyst") is True
    assert is_recommendation_capable("portfolio-manager") is True

    assert is_recommendation_capable("macro-regime-detector") is False
    assert is_recommendation_capable("economic-calendar-fetcher") is False
    assert is_recommendation_capable("dual-axis-skill-reviewer") is False
