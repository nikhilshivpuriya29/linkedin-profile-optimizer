"""Property-based tests for content constraints (Properties 12, 13, 15).

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.3**

These tests verify:
- Property 12: Content generation targets correct sections — content is only
  generated for sections scoring below 70
- Property 13: Generated content respects character and structural constraints —
  headline ≤220 chars, about ≤2600 chars, ≥3 post ideas, banner ≤5 colors
  and tagline ≤10 words
- Property 15: GitHub integration limit — at most 5 GitHub achievements in content
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent
from linkedin_optimizer.models import (
    ContentPackage,
    FactorScore,
    GitHubContributions,
    GitHubData,
    GitHubRepo,
    OptimizationReport,
    PostIdea,
    ProfileData,
    Priority,
    Recommendation,
    SectionInsight,
    SectionScore,
)


# =============================================================================
# Custom Strategies
# =============================================================================


# Skill-like dicts
skill_entry = st.fixed_dictionaries({
    "name": st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs")),
        min_size=2,
        max_size=30,
    ),
    "endorsements": st.integers(min_value=0, max_value=99),
})

# Experience entry with title, company, description
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


@st.composite
def profile_data_strategy(draw):
    """Generate ProfileData instances with sufficient content for content generation."""
    headline = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=5,
        max_size=100,
    ))
    about = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "Nd", "Zs", "Po")),
        min_size=20,
        max_size=300,
    ))
    experience = draw(st.lists(experience_entry, min_size=1, max_size=3))
    skills = draw(st.lists(skill_entry, min_size=2, max_size=8))
    follower_count = draw(st.integers(min_value=50, max_value=5000))

    return ProfileData(
        headline=headline,
        about=about,
        experience=experience,
        skills=skills,
        endorsements=[],
        posts=[],
        banner_url=None,
        photo_url=None,
        education=[],
        certifications=[],
        follower_count=follower_count,
        connection_count=draw(st.integers(min_value=10, max_value=2000)),
        profile_views=None,
    )


# Section names used in the system
SECTION_NAMES = ["headline", "about", "experience", "skills", "posts"]


@st.composite
def section_score_strategy(draw, section_name=None, score=None):
    """Generate a SectionScore with given or random values."""
    name = section_name or draw(st.sampled_from(SECTION_NAMES))
    overall = score if score is not None else draw(st.integers(min_value=0, max_value=100))
    return SectionScore(
        section_name=name,
        overall_score=overall,
        factor_scores=[
            FactorScore(factor_name="test_factor", score=overall, explanation="Test")
        ],
        missing=False,
        excluded_factors=[],
    )


@st.composite
def section_insight_strategy(draw, section_name=None):
    """Generate a SectionInsight for testing."""
    name = section_name or draw(st.sampled_from(SECTION_NAMES))
    return SectionInsight(
        section_name=name,
        strengths=["Good structure"],
        weaknesses=["Needs improvement"],
        recommendations=[
            Recommendation(
                element=name,
                modification="Improve content",
                priority=Priority.HIGH,
                guideline_reference="LinkedIn best practices",
                expected_impact="Higher engagement",
            )
        ],
    )


@st.composite
def optimization_report_strategy(draw):
    """Generate OptimizationReport with varied section scores.

    Ensures at least one section is below 70 and at least one is above 70
    so we can test targeting logic meaningfully.
    """
    # Generate scores for each section — at least one low and one high
    low_sections = draw(st.lists(
        st.sampled_from(SECTION_NAMES),
        min_size=1,
        max_size=3,
        unique=True,
    ))
    all_sections_set = set(SECTION_NAMES)
    high_sections = list(all_sections_set - set(low_sections))

    # Need at least one high section for testing
    assume(len(high_sections) >= 1)

    sections = []
    insights = []

    for name in low_sections:
        score = draw(st.integers(min_value=0, max_value=69))
        sections.append(SectionScore(
            section_name=name,
            overall_score=score,
            factor_scores=[FactorScore(factor_name="f1", score=score, explanation="")],
            missing=False,
            excluded_factors=[],
        ))
        insights.append(SectionInsight(
            section_name=name,
            strengths=["Has content"],
            weaknesses=["Below threshold"],
            recommendations=[
                Recommendation(
                    element=name,
                    modification="Optimize",
                    priority=Priority.HIGH,
                    guideline_reference="LinkedIn guide",
                    expected_impact="Better visibility",
                ),
                Recommendation(
                    element=name,
                    modification="Enhance",
                    priority=Priority.MEDIUM,
                    guideline_reference="Profile tips",
                    expected_impact="More engagement",
                ),
            ],
        ))

    for name in high_sections:
        score = draw(st.integers(min_value=70, max_value=100))
        sections.append(SectionScore(
            section_name=name,
            overall_score=score,
            factor_scores=[FactorScore(factor_name="f1", score=score, explanation="")],
            missing=False,
            excluded_factors=[],
        ))
        insights.append(SectionInsight(
            section_name=name,
            strengths=["Well optimized"],
            weaknesses=["Minor issues"],
            recommendations=[
                Recommendation(
                    element=name,
                    modification="Fine-tune",
                    priority=Priority.LOW,
                    guideline_reference="LinkedIn guide",
                    expected_impact="Marginal improvement",
                ),
            ],
        ))

    overall = sum(s.overall_score for s in sections) // len(sections) if sections else 0

    return OptimizationReport(
        sections=sections,
        insights=insights,
        overall_score=overall,
        github_summary=None,
        excluded_sections=[],
        generated_at="2025-01-01T00:00:00",
    )


@st.composite
def github_data_strategy(draw):
    """Generate GitHubData with varying numbers of repos and achievements."""
    num_repos = draw(st.integers(min_value=0, max_value=15))
    repos = []
    notable_repos = []

    for i in range(num_repos):
        stars = draw(st.integers(min_value=0, max_value=500))
        is_pinned = draw(st.booleans())
        repo = GitHubRepo(
            name=f"repo-{i}",
            description=f"Description for repo {i}",
            stars=stars,
            primary_language="Python",
            is_pinned=is_pinned,
            url=f"https://github.com/user/repo-{i}",
        )
        repos.append(repo)
        if stars >= 5 or is_pinned:
            notable_repos.append(repo)

    return GitHubData(
        repos=repos,
        contributions=GitHubContributions(
            total_commits_12m=draw(st.integers(min_value=0, max_value=2000)),
            total_prs_12m=draw(st.integers(min_value=0, max_value=200)),
            total_issues_12m=draw(st.integers(min_value=0, max_value=100)),
            commits_per_week_avg=draw(st.floats(min_value=0, max_value=50)),
        ),
        pinned_repos=[r for r in repos if r.is_pinned][:6],
        languages={"Python": 50, "TypeScript": 30},
        notable_repos=notable_repos,
    )


# =============================================================================
# Property 12: Content generation targets correct sections
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty12ContentTargetsCorrectSections:
    """Property 12: Content generation targets correct sections.

    **Validates: Requirements 4.1**

    For any Optimization Report, the Content Package should contain content
    suggestions for exactly those sections that scored below 70, and should
    not contain suggestions for sections scoring 70 or above.
    """

    @given(
        report=optimization_report_strategy(),
        profile=profile_data_strategy(),
    )
    @settings(max_examples=30, deadline=None)
    async def test_content_only_for_sections_below_70(
        self, report: OptimizationReport, profile: ProfileData
    ):
        """Content is generated only for sections with score < 70."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        package = await agent.generate(report, profile)

        # Determine which sections scored below 70
        low_sections = {
            s.section_name for s in report.sections if s.overall_score < 70
        }
        high_sections = {
            s.section_name for s in report.sections if s.overall_score >= 70
        }

        # Headline should only be generated if "headline" is in low_sections
        if "headline" not in low_sections:
            assert package.headline is None, (
                "Headline was generated but 'headline' section scored >= 70"
            )

        # About should only be generated if "about" is in low_sections
        if "about" not in low_sections:
            assert package.about is None, (
                "About was generated but 'about' section scored >= 70"
            )

        # Experience should only be generated if "experience" is in low_sections
        if "experience" not in low_sections:
            assert len(package.experience) == 0, (
                "Experience was generated but 'experience' section scored >= 70"
            )

    @given(
        report=optimization_report_strategy(),
        profile=profile_data_strategy(),
    )
    @settings(max_examples=30, deadline=None)
    async def test_low_scoring_sections_get_content(
        self, report: OptimizationReport, profile: ProfileData
    ):
        """Sections scoring below 70 should have content generated."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        package = await agent.generate(report, profile)

        low_sections = {
            s.section_name for s in report.sections if s.overall_score < 70
        }

        # If headline scored below 70, content should be generated
        if "headline" in low_sections:
            assert package.headline is not None, (
                "Headline section scored < 70 but no headline content was generated"
            )

        # If about scored below 70, content should be generated
        if "about" in low_sections:
            assert package.about is not None, (
                "About section scored < 70 but no about content was generated"
            )

        # If experience scored below 70, content should be generated
        if "experience" in low_sections:
            assert len(package.experience) > 0, (
                "Experience section scored < 70 but no experience content was generated"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=20, deadline=None)
    async def test_no_content_when_all_sections_above_70(self, profile: ProfileData):
        """When all sections score >= 70, the package should be empty."""
        # Create report where all sections score >= 70
        sections = [
            SectionScore(
                section_name=name,
                overall_score=85,
                factor_scores=[FactorScore(factor_name="f1", score=85, explanation="")],
                missing=False,
                excluded_factors=[],
            )
            for name in SECTION_NAMES
        ]
        insights = [
            SectionInsight(
                section_name=name,
                strengths=["Good"],
                weaknesses=["Minor"],
                recommendations=[],
            )
            for name in SECTION_NAMES
        ]
        report = OptimizationReport(
            sections=sections,
            insights=insights,
            overall_score=85,
            generated_at="2025-01-01T00:00:00",
        )

        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        package = await agent.generate(report, profile)

        assert package.headline is None
        assert package.about is None
        assert len(package.experience) == 0
        assert len(package.post_ideas) == 0
        assert package.banner is None


# =============================================================================
# Property 13: Generated content respects character and structural constraints
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty13ContentStructuralConstraints:
    """Property 13: Generated content respects character and structural constraints.

    **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6**

    For any generated Content Package:
    - Headline text ≤ 220 characters
    - About text ≤ 2600 characters
    - Post ideas ≥ 3 entries
    - Banner ≤ 5 colors and tagline ≤ 10 words
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_headline_within_220_chars(self, profile: ProfileData):
        """Generated headline text must be ≤ 220 characters."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        # Create a report with headline scoring below 70
        report = self._make_report_with_low_section("headline")
        package = await agent.generate(report, profile)

        if package.headline is not None:
            assert len(package.headline.text) <= 220, (
                f"Headline is {len(package.headline.text)} chars, exceeds 220 limit"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_about_within_2600_chars(self, profile: ProfileData):
        """Generated about text must be ≤ 2600 characters."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        report = self._make_report_with_low_section("about")
        package = await agent.generate(report, profile)

        if package.about is not None:
            assert len(package.about.text) <= 2600, (
                f"About is {len(package.about.text)} chars, exceeds 2600 limit"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_at_least_3_post_ideas(self, profile: ProfileData):
        """At least 3 post ideas must be generated when content is produced."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        # Trigger content generation with a low-scoring section
        report = self._make_report_with_low_section("headline")
        package = await agent.generate(report, profile)

        if package.post_ideas:
            assert len(package.post_ideas) >= 3, (
                f"Only {len(package.post_ideas)} post ideas generated, need >= 3"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_banner_max_5_colors(self, profile: ProfileData):
        """Banner color palette must have ≤ 5 colors."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        report = self._make_report_with_low_section("headline")
        package = await agent.generate(report, profile)

        if package.banner is not None:
            assert len(package.banner.color_palette) <= 5, (
                f"Banner has {len(package.banner.color_palette)} colors, max is 5"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_banner_tagline_max_10_words(self, profile: ProfileData):
        """Banner tagline must have ≤ 10 words."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        report = self._make_report_with_low_section("headline")
        package = await agent.generate(report, profile)

        if package.banner is not None:
            word_count = len(package.banner.tagline.split())
            assert word_count <= 10, (
                f"Banner tagline has {word_count} words, max is 10: "
                f"'{package.banner.tagline}'"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_experience_within_2000_chars_per_position(self, profile: ProfileData):
        """Each experience suggestion bullet text must be ≤ 2000 chars."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        report = self._make_report_with_low_section("experience")
        package = await agent.generate(report, profile)

        for exp in package.experience:
            total_text = "\n".join(exp.bullets)
            assert len(total_text) <= 2000, (
                f"Experience '{exp.role_title}' has {len(total_text)} chars, "
                f"exceeds 2000 limit per position"
            )

    @given(profile=profile_data_strategy())
    @settings(max_examples=30, deadline=None)
    async def test_post_ideas_have_required_fields(self, profile: ProfileData):
        """Each post idea must have non-empty topic, format, and outline of ≥2 sentences."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        report = self._make_report_with_low_section("headline")
        package = await agent.generate(report, profile)

        for idea in package.post_ideas:
            assert idea.topic and len(idea.topic.strip()) > 0, (
                "Post idea has empty topic"
            )
            assert idea.format and len(idea.format.strip()) > 0, (
                "Post idea has empty format"
            )
            assert idea.content_outline and len(idea.content_outline.strip()) > 0, (
                "Post idea has empty content_outline"
            )
            # Outline should be at least 2 sentences (contains at least one period
            # followed by a space or end-of-string, indicating sentence boundaries)
            sentences = [
                s.strip() for s in idea.content_outline.split(".")
                if s.strip()
            ]
            assert len(sentences) >= 2, (
                f"Post idea outline has fewer than 2 sentences: "
                f"'{idea.content_outline}'"
            )

    # -------------------------------------------------------------------------
    # Helper
    # -------------------------------------------------------------------------

    @staticmethod
    def _make_report_with_low_section(section_name: str) -> OptimizationReport:
        """Create a report where the specified section scores below 70."""
        sections = []
        insights = []

        for name in SECTION_NAMES:
            score = 40 if name == section_name else 85
            sections.append(SectionScore(
                section_name=name,
                overall_score=score,
                factor_scores=[
                    FactorScore(factor_name="f1", score=score, explanation="")
                ],
                missing=False,
                excluded_factors=[],
            ))
            insights.append(SectionInsight(
                section_name=name,
                strengths=["Has content"],
                weaknesses=["Needs improvement"],
                recommendations=[
                    Recommendation(
                        element=name,
                        modification="Optimize content",
                        priority=Priority.HIGH,
                        guideline_reference="LinkedIn guide",
                        expected_impact="Better engagement",
                    ),
                    Recommendation(
                        element=name,
                        modification="Enhance",
                        priority=Priority.MEDIUM,
                        guideline_reference="Profile tips",
                        expected_impact="More visibility",
                    ),
                ],
            ))

        return OptimizationReport(
            sections=sections,
            insights=insights,
            overall_score=60,
            generated_at="2025-01-01T00:00:00",
        )


# =============================================================================
# Property 15: GitHub integration limit
# =============================================================================


@pytest.mark.property
@pytest.mark.asyncio
class TestProperty15GitHubIntegrationLimit:
    """Property 15: GitHub integration limit.

    **Validates: Requirements 7.3**

    For any Content Package that incorporates GitHub data, the number of
    GitHub-derived achievements referenced should be at most 5.
    """

    @given(
        profile=profile_data_strategy(),
        github=github_data_strategy(),
    )
    @settings(max_examples=30, deadline=None)
    async def test_at_most_5_github_achievements_in_experience(
        self, profile: ProfileData, github: GitHubData
    ):
        """Experience content incorporates at most 5 GitHub achievements."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )

        # Create report with experience scoring below 70
        report = self._make_report_with_low_experience()
        package = await agent.generate(report, profile, github)

        # Count GitHub-derived bullets across all experience entries
        github_achievement_count = 0
        for exp in package.experience:
            for bullet in exp.bullets:
                # GitHub achievements are incorporated with "open-source" or repo
                # names from the github data
                if "open-source" in bullet.lower() or "contributed to" in bullet.lower():
                    github_achievement_count += 1

        assert github_achievement_count <= 5, (
            f"Found {github_achievement_count} GitHub achievements in experience, "
            f"max allowed is 5"
        )

    @given(github=github_data_strategy())
    @settings(max_examples=50, deadline=None)
    async def test_get_github_achievements_returns_at_most_5(
        self, github: GitHubData
    ):
        """The _get_github_achievements helper returns at most 5 items."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        achievements = agent._get_github_achievements(github)

        assert len(achievements) <= 5, (
            f"Got {len(achievements)} GitHub achievements, max is 5"
        )

    @settings(max_examples=20, deadline=None)
    @given(profile=profile_data_strategy())
    async def test_no_github_achievements_without_github_data(
        self, profile: ProfileData
    ):
        """Without GitHub data, no GitHub achievements appear in content."""
        agent = ContentCreatorAgent(
            model_id="test", fallback_model_id="test", hf_client=None
        )
        achievements = agent._get_github_achievements(None)
        assert achievements == [], "Expected empty list when no GitHub data provided"

    # -------------------------------------------------------------------------
    # Helper
    # -------------------------------------------------------------------------

    @staticmethod
    def _make_report_with_low_experience() -> OptimizationReport:
        """Create a report where experience scores below 70."""
        sections = []
        insights = []

        for name in SECTION_NAMES:
            score = 40 if name == "experience" else 85
            sections.append(SectionScore(
                section_name=name,
                overall_score=score,
                factor_scores=[
                    FactorScore(factor_name="f1", score=score, explanation="")
                ],
                missing=False,
                excluded_factors=[],
            ))
            insights.append(SectionInsight(
                section_name=name,
                strengths=["Has content"],
                weaknesses=["Needs improvement"],
                recommendations=[
                    Recommendation(
                        element=name,
                        modification="Optimize",
                        priority=Priority.HIGH,
                        guideline_reference="LinkedIn guide",
                        expected_impact="Better engagement",
                    ),
                    Recommendation(
                        element=name,
                        modification="Enhance",
                        priority=Priority.MEDIUM,
                        guideline_reference="Profile tips",
                        expected_impact="More visibility",
                    ),
                ],
            ))

        return OptimizationReport(
            sections=sections,
            insights=insights,
            overall_score=60,
            generated_at="2025-01-01T00:00:00",
        )
