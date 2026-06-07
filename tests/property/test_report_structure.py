"""Property-based tests for report structure (Properties 9, 10, 11).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

These tests verify:
- Property 9: Optimization report structural completeness — at least 1 strength,
  1 weakness, 1 recommendation per section; at least 2 recommendations if score < 70
- Property 10: Recommendations are ordered by priority — High before Medium before Low
- Property 11: Every recommendation cites a guideline — guideline_reference is non-empty
"""

import asyncio
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.agents.analyzer_agent import AnalyzerAgent
from linkedin_optimizer.models import (
    Priority,
    ProfileData,
    OptimizationReport,
    SectionInsight,
)


# =============================================================================
# Custom Strategies
# =============================================================================

safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=200,
)

non_empty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=100,
)

# Experience-like dicts with title, company, and description
experience_entry = st.fixed_dictionaries({
    "title": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=3,
        max_size=50,
    ),
    "company": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=3,
        max_size=50,
    ),
    "description": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=10,
        max_size=200,
    ),
})

# Skill-like dicts
skill_entry = st.fixed_dictionaries({
    "name": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=2,
        max_size=30,
    ),
    "endorsements": st.integers(min_value=0, max_value=99),
})

# Post-like dicts
post_entry = st.fixed_dictionaries({
    "text": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=10,
        max_size=200,
    ),
    "reactions": st.integers(min_value=0, max_value=500),
    "comments": st.integers(min_value=0, max_value=100),
})

url_strategy = st.just("https://example.com/image.png")


@st.composite
def profile_data_strategy(draw):
    """Generate ProfileData instances with varied content.

    Ensures at least some content is present so the analyzer has
    something to score across multiple sections.
    """
    headline = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=5,
        max_size=220,
    ))
    about = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=20,
        max_size=500,
    ))
    experience = draw(st.lists(experience_entry, min_size=1, max_size=3))
    skills = draw(st.lists(skill_entry, min_size=1, max_size=10))
    posts = draw(st.lists(post_entry, min_size=0, max_size=5))
    banner_url = draw(st.one_of(st.none(), url_strategy))
    photo_url = draw(st.one_of(st.none(), url_strategy))
    follower_count = draw(st.integers(min_value=0, max_value=50000))

    return ProfileData(
        headline=headline,
        about=about,
        experience=experience,
        skills=skills,
        endorsements=[],
        posts=posts,
        banner_url=banner_url,
        photo_url=photo_url,
        education=[],
        certifications=[],
        follower_count=follower_count,
        connection_count=draw(st.integers(min_value=0, max_value=5000)),
        profile_views=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10000))),
    )


# =============================================================================
# Helper: Priority ordering map
# =============================================================================

_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


# =============================================================================
# Property 9: Optimization report structural completeness
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty9ReportStructuralCompleteness:
    """Property 9: Optimization report structural completeness.

    **Validates: Requirements 3.1, 3.3**

    For any ProfileData with content, the generated OptimizationReport must have:
    - At least 1 strength per section insight
    - At least 1 weakness per section insight
    - At least 1 recommendation per section insight
    - At least 2 recommendations for any section scoring below 70
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_at_least_one_strength_per_insight(self, profile: ProfileData):
        """Every section insight contains at least 1 strength."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        for insight in report.insights:
            assert len(insight.strengths) >= 1, (
                f"Section '{insight.section_name}' has no strengths"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_at_least_one_weakness_per_insight(self, profile: ProfileData):
        """Every section insight contains at least 1 weakness."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        for insight in report.insights:
            assert len(insight.weaknesses) >= 1, (
                f"Section '{insight.section_name}' has no weaknesses"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_at_least_one_recommendation_per_insight(self, profile: ProfileData):
        """Every section insight contains at least 1 recommendation."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        for insight in report.insights:
            assert len(insight.recommendations) >= 1, (
                f"Section '{insight.section_name}' has no recommendations"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_low_score_sections_have_at_least_two_recommendations(
        self, profile: ProfileData
    ):
        """Sections scoring below 70 must have at least 2 recommendations."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        # Build a map of section scores for lookup
        section_score_map = {s.section_name: s.overall_score for s in report.sections}

        for insight in report.insights:
            section_score = section_score_map.get(insight.section_name, 0)
            if section_score < 70:
                assert len(insight.recommendations) >= 2, (
                    f"Section '{insight.section_name}' scored {section_score} (< 70) "
                    f"but has only {len(insight.recommendations)} recommendation(s), "
                    f"expected at least 2"
                )


# =============================================================================
# Property 10: Recommendations are ordered by priority
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty10RecommendationPriorityOrder:
    """Property 10: Recommendations are ordered by priority.

    **Validates: Requirements 3.2**

    For each section insight's recommendations list, all HIGH priority items
    must appear before MEDIUM, and all MEDIUM before LOW.
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_recommendations_ordered_high_before_medium_before_low(
        self, profile: ProfileData
    ):
        """Recommendations are ordered: HIGH > MEDIUM > LOW."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        for insight in report.insights:
            priorities = [r.priority for r in insight.recommendations]
            priority_values = [_PRIORITY_ORDER[p] for p in priorities]

            # Verify the list is non-decreasing (sorted by priority order)
            for i in range(len(priority_values) - 1):
                assert priority_values[i] <= priority_values[i + 1], (
                    f"Section '{insight.section_name}' has recommendations "
                    f"out of priority order: {priorities}"
                )


# =============================================================================
# Property 11: Every recommendation cites a guideline
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty11GuidelineReference:
    """Property 11: Every recommendation cites a guideline.

    **Validates: Requirements 3.4**

    For every recommendation in every section insight, the guideline_reference
    field must be a non-empty string referencing a LinkedIn optimization guideline.
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_all_recommendations_have_non_empty_guideline_reference(
        self, profile: ProfileData
    ):
        """Every recommendation has a non-empty guideline_reference."""
        agent = AnalyzerAgent(model_id="test", fallback_model_id="test", hf_client=None)
        report = await agent.analyze(profile)

        for insight in report.insights:
            for rec in insight.recommendations:
                assert rec.guideline_reference is not None, (
                    f"Section '{insight.section_name}': recommendation "
                    f"'{rec.element}' has None guideline_reference"
                )
                assert isinstance(rec.guideline_reference, str), (
                    f"Section '{insight.section_name}': recommendation "
                    f"'{rec.element}' guideline_reference is not a string"
                )
                assert len(rec.guideline_reference.strip()) > 0, (
                    f"Section '{insight.section_name}': recommendation "
                    f"'{rec.element}' has empty guideline_reference"
                )
