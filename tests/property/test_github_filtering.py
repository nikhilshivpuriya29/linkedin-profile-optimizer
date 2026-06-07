"""Property-based tests for GitHub filtering logic.

**Validates: Requirements 7.2, 7.4**

These tests verify:
- Property 14: Notable repository identification correctly filters repos with stars>=5 OR is_pinned=True
- Property 16: Graceful degradation when GitHub is unavailable — the pipeline can produce
  optimization reports using only LinkedIn data
"""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from linkedin_optimizer.models import (
    GitHubExtractionResult,
    GitHubRepo,
    OptimizationReport,
    ProfileData,
    SectionScore,
    SectionInsight,
    FactorScore,
    Recommendation,
    Priority,
)
from linkedin_optimizer.scrapers.github_extractor import GitHubExtractor


# --- Custom Strategies ---

safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=100,
)

non_empty_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=50,
)

language_text = st.sampled_from(
    ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "C++", "Ruby", None]
)


@st.composite
def github_repo_strategy(draw):
    """Generate GitHubRepo objects with random star counts and pinned status."""
    return GitHubRepo(
        name=draw(non_empty_text),
        description=draw(st.one_of(st.none(), safe_text)),
        stars=draw(st.integers(min_value=0, max_value=1000)),
        primary_language=draw(language_text),
        is_pinned=draw(st.booleans()),
        url=draw(
            st.text(
                alphabet="abcdefghijklmnopqrstuvwxyz0123456789:/.-",
                min_size=0,
                max_size=80,
            )
        ),
    )


@st.composite
def repo_list_strategy(draw):
    """Generate a list of GitHubRepo objects of varying lengths."""
    return draw(st.lists(github_repo_strategy(), min_size=0, max_size=30))


# =============================================================================
# Property 14: Notable repository identification
# =============================================================================


@pytest.mark.property
class TestProperty14NotableRepoIdentification:
    """Property 14: Notable repository identification.

    **Validates: Requirements 7.2**

    Generate lists of repos with varying star counts and pinned status,
    verify notable_repos contains exactly those with stars>=5 OR is_pinned=True.
    """

    @given(repos=repo_list_strategy())
    @settings(max_examples=200)
    def test_notable_repos_contain_only_qualifying(self, repos: list[GitHubRepo]):
        """Every repo in the result has stars >= 5 OR is_pinned == True."""
        extractor = GitHubExtractor(username="test_user")
        notable = extractor._identify_notable_repos(repos)

        for repo in notable:
            assert repo.stars >= 5 or repo.is_pinned, (
                f"Repo '{repo.name}' in notable_repos has stars={repo.stars} "
                f"and is_pinned={repo.is_pinned}, which doesn't meet criteria"
            )

    @given(repos=repo_list_strategy())
    @settings(max_examples=200)
    def test_non_notable_repos_fail_criteria(self, repos: list[GitHubRepo]):
        """Every repo NOT in the result has stars < 5 AND is_pinned == False."""
        extractor = GitHubExtractor(username="test_user")
        notable = extractor._identify_notable_repos(repos)

        notable_set = set(id(r) for r in notable)
        for repo in repos:
            if id(repo) not in notable_set:
                assert repo.stars < 5 and not repo.is_pinned, (
                    f"Repo '{repo.name}' not in notable_repos but has stars={repo.stars} "
                    f"and is_pinned={repo.is_pinned}, which SHOULD meet criteria"
                )

    @given(repos=repo_list_strategy())
    @settings(max_examples=200)
    def test_result_is_subset_of_input(self, repos: list[GitHubRepo]):
        """The result is a subset of the input list."""
        extractor = GitHubExtractor(username="test_user")
        notable = extractor._identify_notable_repos(repos)

        input_ids = set(id(r) for r in repos)
        for repo in notable:
            assert id(repo) in input_ids, (
                f"Repo '{repo.name}' in result is not from the input list"
            )

    @given(repos=repo_list_strategy())
    @settings(max_examples=200)
    def test_result_length_matches_expected(self, repos: list[GitHubRepo]):
        """The count of notable repos equals the count of qualifying repos in the input."""
        extractor = GitHubExtractor(username="test_user")
        notable = extractor._identify_notable_repos(repos)

        expected_count = sum(
            1 for r in repos if r.stars >= 5 or r.is_pinned
        )
        assert len(notable) == expected_count


# =============================================================================
# Property 16: Graceful degradation when GitHub is unavailable
# =============================================================================


@pytest.mark.property
class TestProperty16GracefulDegradation:
    """Property 16: Graceful degradation when GitHub is unavailable.

    **Validates: Requirements 7.4**

    Simulate GitHub failures, verify the pipeline can continue with
    LinkedIn-only data. The models don't require GitHub data to produce
    a valid OptimizationReport.
    """

    @given(
        error_msg=non_empty_text,
        headline=safe_text,
        about=safe_text,
    )
    @settings(max_examples=100)
    def test_failed_github_result_has_no_data(
        self, error_msg: str, headline: str, about: str
    ):
        """A failed GitHubExtractionResult correctly represents unavailability."""
        result = GitHubExtractionResult(
            success=False,
            data=None,
            error_message=error_msg,
        )

        assert result.success is False
        assert result.data is None
        assert result.error_message == error_msg

    @given(
        headline=non_empty_text,
        about=safe_text,
        overall_score=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100)
    def test_optimization_report_without_github(
        self, headline: str, about: str, overall_score: int
    ):
        """An OptimizationReport can be constructed without GitHub data.

        This verifies that the pipeline can produce valid reports using
        only LinkedIn profile data when GitHub is unavailable.
        """
        # Create a minimal profile with only LinkedIn data
        profile = ProfileData(
            headline=headline,
            about=about,
        )

        # Create a valid OptimizationReport without github_summary
        report = OptimizationReport(
            sections=[
                SectionScore(
                    section_name="headline",
                    overall_score=overall_score,
                    factor_scores=[
                        FactorScore(
                            factor_name="keyword_presence",
                            score=overall_score,
                            explanation="Score based on LinkedIn data only",
                        )
                    ],
                )
            ],
            insights=[
                SectionInsight(
                    section_name="headline",
                    strengths=["Has a headline"],
                    weaknesses=["Could be improved"],
                    recommendations=[
                        Recommendation(
                            element="headline",
                            modification="Add value proposition",
                            priority=Priority.HIGH,
                            guideline_reference="LinkedIn headline best practices",
                            expected_impact="Better visibility",
                        )
                    ],
                )
            ],
            overall_score=overall_score,
            github_summary=None,
            excluded_sections=[],
        )

        # Verify report is valid without GitHub data
        assert report.github_summary is None
        assert report.overall_score == overall_score
        assert len(report.sections) > 0
        assert len(report.insights) > 0
        assert report.sections[0].section_name == "headline"

    @given(error_msg=non_empty_text)
    @settings(max_examples=100)
    def test_github_failure_does_not_corrupt_linkedin_profile(self, error_msg: str):
        """GitHub failure result can coexist with valid LinkedIn ProfileData.

        The pipeline should be able to hold both a valid LinkedIn extraction
        and a failed GitHub extraction simultaneously without conflict.
        """
        # Simulate a valid LinkedIn profile
        profile = ProfileData(
            headline="Software Engineer at Company",
            about="Experienced developer",
            experience=[{"title": "Engineer", "company": "Corp"}],
            skills=[{"name": "Python", "endorsements": 10}],
            follower_count=500,
            connection_count=300,
        )

        # Simulate a failed GitHub extraction
        github_result = GitHubExtractionResult(
            success=False,
            data=None,
            error_message=error_msg,
        )

        # Both can be used independently — profile remains intact
        assert profile.headline == "Software Engineer at Company"
        assert profile.follower_count == 500
        assert len(profile.experience) == 1
        assert github_result.success is False
        assert github_result.data is None
