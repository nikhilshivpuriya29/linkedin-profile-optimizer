"""Property-based tests for data model serialization round-trips.

**Validates: Requirements 1.2, 1.3, 1.7**

These tests use Hypothesis to generate arbitrary model instances and verify
that serialization (to_dict) followed by deserialization (from_dict) produces
equivalent objects — no fields lost, no data corrupted.
"""

import json
import pytest
from datetime import datetime, timedelta
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalStatus,
    ContentPackage,
    ExtractionResult,
    GitHubContributions,
    GitHubData,
    GitHubRepo,
    HeadlineSuggestion,
    AboutSuggestion,
    BannerSuggestion,
    ExperienceSuggestion,
    PostIdea,
    OptimizationReport,
    FactorScore,
    SectionScore,
    Recommendation,
    SectionInsight,
    PipelineStatus,
    Priority,
    ProfileData,
    RunMetadata,
)


# --- Custom Strategies ---

# Reusable text strategies
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

url_text = st.from_regex(r"https://[a-z0-9]+\.[a-z]{2,4}/[a-z0-9/]*", fullmatch=True)

optional_url = st.one_of(st.none(), url_text)

# Simple dict strategy for profile list fields
simple_dict = st.fixed_dictionaries(
    {"key": non_empty_text, "value": non_empty_text}
)

simple_dict_list = st.lists(simple_dict, min_size=0, max_size=5)


# --- ProfileData Strategy ---

@st.composite
def profile_data_strategy(draw):
    """Generate arbitrary ProfileData instances with all field variations."""
    return ProfileData(
        headline=draw(safe_text),
        about=draw(safe_text),
        experience=draw(simple_dict_list),
        skills=draw(simple_dict_list),
        endorsements=draw(simple_dict_list),
        posts=draw(simple_dict_list),
        banner_url=draw(optional_url),
        photo_url=draw(optional_url),
        education=draw(simple_dict_list),
        certifications=draw(simple_dict_list),
        follower_count=draw(st.integers(min_value=0, max_value=10_000_000)),
        connection_count=draw(st.integers(min_value=0, max_value=30_000)),
        profile_views=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1_000_000))),
    )


# --- ExtractionResult Strategy ---

@st.composite
def extraction_result_strategy(draw):
    """Generate arbitrary ExtractionResult instances."""
    success = draw(st.booleans())
    if success:
        profile_data = draw(profile_data_strategy())
        failed_sections = []
        error_message = None
    else:
        # On failure, profile_data can be None or populated (partial failure)
        profile_data = draw(st.one_of(st.none(), profile_data_strategy()))
        failed_sections = draw(st.lists(non_empty_text, min_size=0, max_size=5))
        error_message = draw(st.one_of(st.none(), non_empty_text))
    return ExtractionResult(
        success=success,
        profile_data=profile_data,
        failed_sections=failed_sections,
        error_message=error_message,
    )


# --- GitHubData Strategy ---

@st.composite
def github_repo_strategy(draw):
    return GitHubRepo(
        name=draw(non_empty_text),
        description=draw(st.one_of(st.none(), safe_text)),
        stars=draw(st.integers(min_value=0, max_value=100_000)),
        primary_language=draw(st.one_of(st.none(), non_empty_text)),
        is_pinned=draw(st.booleans()),
        url=draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789:/.", min_size=0, max_size=80)),
    )


@st.composite
def github_contributions_strategy(draw):
    return GitHubContributions(
        total_commits_12m=draw(st.integers(min_value=0, max_value=10_000)),
        total_prs_12m=draw(st.integers(min_value=0, max_value=5_000)),
        total_issues_12m=draw(st.integers(min_value=0, max_value=5_000)),
        commits_per_week_avg=draw(st.floats(min_value=0.0, max_value=200.0, allow_nan=False, allow_infinity=False)),
    )


@st.composite
def github_data_strategy(draw):
    repos = draw(st.lists(github_repo_strategy(), min_size=0, max_size=5))
    return GitHubData(
        repos=repos,
        contributions=draw(github_contributions_strategy()),
        pinned_repos=draw(st.lists(github_repo_strategy(), min_size=0, max_size=3)),
        languages=draw(st.dictionaries(non_empty_text, st.integers(min_value=0, max_value=1_000_000), max_size=5)),
        notable_repos=draw(st.lists(github_repo_strategy(), min_size=0, max_size=3)),
    )


# --- OptimizationReport Strategy ---

@st.composite
def factor_score_strategy(draw):
    return FactorScore(
        factor_name=draw(non_empty_text),
        score=draw(st.integers(min_value=0, max_value=100)),
        explanation=draw(safe_text),
    )


@st.composite
def section_score_strategy(draw):
    return SectionScore(
        section_name=draw(non_empty_text),
        overall_score=draw(st.integers(min_value=0, max_value=100)),
        factor_scores=draw(st.lists(factor_score_strategy(), min_size=0, max_size=5)),
        missing=draw(st.booleans()),
        excluded_factors=draw(st.lists(non_empty_text, min_size=0, max_size=3)),
    )


@st.composite
def recommendation_strategy(draw):
    return Recommendation(
        element=draw(non_empty_text),
        modification=draw(safe_text),
        priority=draw(st.sampled_from(Priority)),
        guideline_reference=draw(safe_text),
        expected_impact=draw(safe_text),
    )


@st.composite
def section_insight_strategy(draw):
    return SectionInsight(
        section_name=draw(non_empty_text),
        strengths=draw(st.lists(safe_text, min_size=0, max_size=3)),
        weaknesses=draw(st.lists(safe_text, min_size=0, max_size=3)),
        recommendations=draw(st.lists(recommendation_strategy(), min_size=0, max_size=3)),
    )


@st.composite
def optimization_report_strategy(draw):
    return OptimizationReport(
        sections=draw(st.lists(section_score_strategy(), min_size=0, max_size=5)),
        insights=draw(st.lists(section_insight_strategy(), min_size=0, max_size=5)),
        overall_score=draw(st.integers(min_value=0, max_value=100)),
        github_summary=draw(st.one_of(st.none(), safe_text)),
        excluded_sections=draw(st.lists(non_empty_text, min_size=0, max_size=3)),
        generated_at=draw(safe_text),
    )


# --- ContentPackage Strategy ---

@st.composite
def headline_suggestion_strategy(draw):
    return HeadlineSuggestion(
        text=draw(safe_text),
        keywords_used=draw(st.lists(non_empty_text, min_size=0, max_size=5)),
        value_proposition=draw(safe_text),
    )


@st.composite
def about_suggestion_strategy(draw):
    return AboutSuggestion(
        text=draw(safe_text),
        hook_sentence=draw(safe_text),
        keywords_used=draw(st.lists(non_empty_text, min_size=0, max_size=5)),
        call_to_action=draw(safe_text),
    )


@st.composite
def experience_suggestion_strategy(draw):
    return ExperienceSuggestion(
        role_title=draw(non_empty_text),
        company=draw(non_empty_text),
        bullets=draw(st.lists(safe_text, min_size=0, max_size=5)),
        metrics_included=draw(st.booleans()),
        qualitative_note=draw(st.one_of(st.none(), safe_text)),
    )


@st.composite
def post_idea_strategy(draw):
    return PostIdea(
        topic=draw(non_empty_text),
        format=draw(st.sampled_from(["text", "carousel", "poll", "video"])),
        content_outline=draw(safe_text),
    )


@st.composite
def banner_suggestion_strategy(draw):
    return BannerSuggestion(
        dimensions=draw(non_empty_text),
        color_palette=draw(st.lists(non_empty_text, min_size=0, max_size=5)),
        tagline=draw(safe_text),
    )


@st.composite
def content_package_strategy(draw):
    return ContentPackage(
        headline=draw(st.one_of(st.none(), headline_suggestion_strategy())),
        about=draw(st.one_of(st.none(), about_suggestion_strategy())),
        experience=draw(st.lists(experience_suggestion_strategy(), min_size=0, max_size=3)),
        post_ideas=draw(st.lists(post_idea_strategy(), min_size=0, max_size=5)),
        banner=draw(st.one_of(st.none(), banner_suggestion_strategy())),
        generated_at=draw(safe_text),
    )


# --- ApprovalItem Strategy ---

# Use a fixed set of reasonable datetimes to avoid edge cases with timezone/microsecond rounding
reasonable_datetimes = st.datetimes(
    min_value=datetime(2020, 1, 1),
    max_value=datetime(2030, 12, 31),
)


@st.composite
def approval_item_strategy(draw):
    created_at = draw(reasonable_datetimes)
    return ApprovalItem(
        item_id=draw(non_empty_text),
        section_name=draw(non_empty_text),
        current_content=draw(safe_text),
        proposed_content=draw(safe_text),
        status=draw(st.sampled_from(ApprovalStatus)),
        user_feedback=draw(st.one_of(st.none(), safe_text)),
        rejection_reason=draw(st.one_of(st.none(), safe_text)),
        created_at=created_at,
        expires_at=draw(st.one_of(st.none(), reasonable_datetimes)),
        decided_at=draw(st.one_of(st.none(), reasonable_datetimes)),
    )


# --- RunMetadata Strategy ---

@st.composite
def run_metadata_strategy(draw):
    return RunMetadata(
        run_id=draw(non_empty_text),
        start_time=draw(reasonable_datetimes),
        end_time=draw(st.one_of(st.none(), reasonable_datetimes)),
        status=draw(st.sampled_from(PipelineStatus)),
        summary=draw(st.one_of(st.none(), safe_text)),
        error=draw(st.one_of(st.none(), safe_text)),
    )


# =============================================================================
# Property 1: Profile data parsing preserves all sections
# =============================================================================


@pytest.mark.property
class TestProperty1ProfileDataParsing:
    """Property 1: Profile data parsing preserves all sections.

    **Validates: Requirements 1.2, 1.3**

    For any valid ProfileData, converting to dict and back should preserve
    every field — no data is lost during the parse cycle.
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=100)
    def test_all_fields_preserved_after_parse(self, profile: ProfileData):
        """All ProfileData fields survive to_dict -> from_dict."""
        parsed = ProfileData.from_dict(profile.to_dict())

        # Verify every field individually to pinpoint failures
        assert parsed.headline == profile.headline
        assert parsed.about == profile.about
        assert parsed.experience == profile.experience
        assert parsed.skills == profile.skills
        assert parsed.endorsements == profile.endorsements
        assert parsed.posts == profile.posts
        assert parsed.banner_url == profile.banner_url
        assert parsed.photo_url == profile.photo_url
        assert parsed.education == profile.education
        assert parsed.certifications == profile.certifications
        assert parsed.follower_count == profile.follower_count
        assert parsed.connection_count == profile.connection_count
        assert parsed.profile_views == profile.profile_views

    @given(profile=profile_data_strategy())
    @settings(max_examples=100)
    def test_no_extra_fields_introduced(self, profile: ProfileData):
        """Parsing does not introduce extra keys beyond the model fields."""
        d = profile.to_dict()
        expected_keys = {
            "headline", "about", "experience", "skills", "endorsements",
            "posts", "banner_url", "photo_url", "education", "certifications",
            "follower_count", "connection_count", "profile_views",
        }
        assert set(d.keys()) == expected_keys


# =============================================================================
# Property 2: Profile data serialization round-trip
# =============================================================================


@pytest.mark.property
class TestProperty2SerializationRoundTrip:
    """Property 2: Profile data serialization round-trip.

    **Validates: Requirements 1.2, 1.3, 1.7**

    For any valid data model, serialize to JSON and deserialize back,
    assert equivalence.
    """

    @given(profile=profile_data_strategy())
    @settings(max_examples=100)
    def test_profile_data_json_round_trip(self, profile: ProfileData):
        """ProfileData survives JSON serialization round-trip."""
        json_str = json.dumps(profile.to_dict())
        restored = ProfileData.from_dict(json.loads(json_str))
        assert restored == profile

    @given(result=extraction_result_strategy())
    @settings(max_examples=100)
    def test_extraction_result_round_trip(self, result: ExtractionResult):
        """ExtractionResult survives to_dict -> from_dict round-trip."""
        json_str = json.dumps(result.to_dict())
        restored = ExtractionResult.from_dict(json.loads(json_str))
        assert restored == result

    @given(data=github_data_strategy())
    @settings(max_examples=100)
    def test_github_data_round_trip(self, data: GitHubData):
        """GitHubData survives JSON serialization round-trip."""
        json_str = json.dumps(data.to_dict())
        restored = GitHubData.from_dict(json.loads(json_str))
        assert restored == data

    @given(report=optimization_report_strategy())
    @settings(max_examples=100)
    def test_optimization_report_round_trip(self, report: OptimizationReport):
        """OptimizationReport survives JSON serialization round-trip."""
        json_str = json.dumps(report.to_dict())
        restored = OptimizationReport.from_dict(json.loads(json_str))
        assert restored == report

    @given(package=content_package_strategy())
    @settings(max_examples=100)
    def test_content_package_round_trip(self, package: ContentPackage):
        """ContentPackage survives JSON serialization round-trip."""
        json_str = json.dumps(package.to_dict())
        restored = ContentPackage.from_dict(json.loads(json_str))
        assert restored == package

    @given(item=approval_item_strategy())
    @settings(max_examples=100)
    def test_approval_item_round_trip(self, item: ApprovalItem):
        """ApprovalItem survives JSON serialization round-trip."""
        json_str = json.dumps(item.to_dict())
        restored = ApprovalItem.from_dict(json.loads(json_str))
        assert restored == item

    @given(meta=run_metadata_strategy())
    @settings(max_examples=100)
    def test_run_metadata_round_trip(self, meta: RunMetadata):
        """RunMetadata survives JSON serialization round-trip."""
        json_str = json.dumps(meta.to_dict())
        restored = RunMetadata.from_dict(json.loads(json_str))
        assert restored == meta
