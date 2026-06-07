"""Property-based tests for engagement calculations (Properties 22, 23).

**Validates: Requirements 8.3, 8.4**

These tests verify:
- Property 22: Engagement comparison calculation correctness — absolute_change
  equals current - baseline, percentage_change = ((current - baseline) / baseline × 100)
  when baseline > 0, and percentage_change = 0.0 when baseline = 0
- Property 23: Section prioritization by historical performance — generate
  engagement reports, verify sections ranked by descending improvement
"""

import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from unittest.mock import MagicMock

from linkedin_optimizer.models import EngagementComparison, EngagementSnapshot
from linkedin_optimizer.persistence import DataStore
from linkedin_optimizer.tracking.engagement_tracker import EngagementTracker


# =============================================================================
# Helpers
# =============================================================================


def _create_tracker() -> EngagementTracker:
    """Create an EngagementTracker with mock dependencies for unit testing."""
    mock_mcp_client = MagicMock()
    mock_data_store = MagicMock()
    return EngagementTracker(mcp_client=mock_mcp_client, data_store=mock_data_store)


def _create_tracker_with_real_store(data_dir: str) -> EngagementTracker:
    """Create an EngagementTracker with a real DataStore for integration testing."""
    mock_mcp_client = MagicMock()
    data_store = DataStore(data_dir)
    return EngagementTracker(mcp_client=mock_mcp_client, data_store=data_store)


# Module-level tracker instance for property tests (stateless helper methods)
_tracker = _create_tracker()


# =============================================================================
# Custom Strategies
# =============================================================================

# Non-negative floats suitable for engagement metrics (avoid inf/nan)
non_negative_floats = st.floats(
    min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False
)

# Positive floats for baseline > 0 cases
positive_floats = st.floats(
    min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False
)

METRIC_NAMES = [
    "profile_views",
    "connection_requests",
    "post_likes",
    "post_comments",
    "post_shares",
    "post_impressions",
]

SECTION_NAMES = ["headline", "about", "experience", "skills", "posts", "banner"]


# =============================================================================
# Property 22: Engagement comparison calculation correctness
# =============================================================================


@pytest.mark.property
class TestProperty22EngagementComparisonCalculation:
    """Property 22: Engagement comparison calculation correctness.

    **Validates: Requirements 8.3**

    For any pair of (baseline, current) engagement values:
    - absolute_change == current - baseline
    - percentage_change == ((current - baseline) / baseline × 100) when baseline > 0
    - percentage_change == 0.0 when baseline == 0
    """

    @given(
        metric_name=st.sampled_from(METRIC_NAMES),
        baseline=positive_floats,
        current=non_negative_floats,
    )
    @settings(max_examples=100, deadline=None)
    def test_absolute_change_equals_current_minus_baseline(
        self, metric_name: str, baseline: float, current: float
    ):
        """absolute_change is always current - baseline."""
        result = _tracker._compute_comparison(metric_name, baseline, current)

        expected_absolute = current - baseline
        assert result.absolute_change == pytest.approx(expected_absolute, rel=1e-9), (
            f"Expected absolute_change={expected_absolute}, got {result.absolute_change} "
            f"for baseline={baseline}, current={current}"
        )

    @given(
        metric_name=st.sampled_from(METRIC_NAMES),
        baseline=positive_floats,
        current=non_negative_floats,
    )
    @settings(max_examples=100, deadline=None)
    def test_percentage_change_formula_when_baseline_positive(
        self, metric_name: str, baseline: float, current: float
    ):
        """percentage_change = ((current - baseline) / baseline × 100) when baseline > 0."""
        result = _tracker._compute_comparison(metric_name, baseline, current)

        expected_percentage = ((current - baseline) / baseline) * 100.0
        assert result.percentage_change == pytest.approx(
            expected_percentage, rel=1e-9
        ), (
            f"Expected percentage_change={expected_percentage}, got {result.percentage_change} "
            f"for baseline={baseline}, current={current}"
        )

    @given(
        metric_name=st.sampled_from(METRIC_NAMES),
        current=non_negative_floats,
    )
    @settings(max_examples=100, deadline=None)
    def test_percentage_change_is_zero_when_baseline_is_zero(
        self, metric_name: str, current: float
    ):
        """percentage_change == 0.0 when baseline == 0."""
        result = _tracker._compute_comparison(metric_name, 0.0, current)

        assert result.percentage_change == 0.0, (
            f"Expected percentage_change=0.0 when baseline=0, "
            f"got {result.percentage_change} for current={current}"
        )
        # absolute_change should still be correct
        assert result.absolute_change == pytest.approx(current - 0.0, rel=1e-9)

    @given(
        metric_name=st.sampled_from(METRIC_NAMES),
        baseline=non_negative_floats,
        current=non_negative_floats,
    )
    @settings(max_examples=100, deadline=None)
    def test_comparison_fields_are_populated_correctly(
        self, metric_name: str, baseline: float, current: float
    ):
        """All fields of EngagementComparison are populated with correct values."""
        result = _tracker._compute_comparison(metric_name, baseline, current)

        assert result.metric_name == metric_name
        assert result.baseline_value == pytest.approx(baseline, rel=1e-9)
        assert result.current_value == pytest.approx(current, rel=1e-9)
        assert result.absolute_change == pytest.approx(current - baseline, rel=1e-9)

    @given(
        metric_name=st.sampled_from(METRIC_NAMES),
        value=non_negative_floats,
    )
    @settings(max_examples=50, deadline=None)
    def test_no_change_yields_zero_absolute_and_percentage(
        self, metric_name: str, value: float
    ):
        """When baseline == current, both absolute_change and percentage_change are 0."""
        result = _tracker._compute_comparison(metric_name, value, value)

        assert result.absolute_change == pytest.approx(0.0, abs=1e-12)
        if value > 0:
            assert result.percentage_change == pytest.approx(0.0, abs=1e-9)
        else:
            assert result.percentage_change == 0.0


# =============================================================================
# Property 23: Section prioritization by historical performance
# =============================================================================


@st.composite
def section_engagement_data(draw):
    """Generate engagement data for multiple sections with distinct improvements.

    Returns a list of tuples: (section_name, baseline_views, current_views,
    baseline_connections, current_connections, baseline_engagement, current_engagement)
    where each section has a unique improvement level.
    """
    num_sections = draw(st.integers(min_value=2, max_value=5))
    sections = draw(
        st.lists(
            st.sampled_from(SECTION_NAMES),
            min_size=num_sections,
            max_size=num_sections,
            unique=True,
        )
    )

    data = []
    for section in sections:
        baseline_views = draw(st.integers(min_value=1, max_value=1000))
        # Generate a multiplier to ensure distinct improvements
        multiplier = draw(
            st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False)
        )
        current_views = int(baseline_views * multiplier)

        baseline_connections = draw(st.integers(min_value=1, max_value=500))
        current_connections = int(baseline_connections * multiplier)

        baseline_likes = draw(st.integers(min_value=0, max_value=200))
        current_likes = int(baseline_likes * multiplier) if baseline_likes > 0 else 0

        data.append(
            (
                section,
                baseline_views,
                current_views,
                baseline_connections,
                current_connections,
                baseline_likes,
                current_likes,
            )
        )

    return data


@pytest.mark.property
class TestProperty23SectionPrioritization:
    """Property 23: Section prioritization by historical performance.

    **Validates: Requirements 8.4**

    Given engagement reports for multiple sections with varying improvements,
    get_top_performing_sections() returns sections ranked by descending
    average improvement.
    """

    @given(data=section_engagement_data())
    @settings(max_examples=50, deadline=None)
    def test_sections_ranked_by_descending_improvement(self, data):
        """Sections are returned in descending order of average improvement."""
        # Create a temporary directory for the DataStore
        tmp_dir = tempfile.mkdtemp()
        try:
            tracker = _create_tracker_with_real_store(tmp_dir)
            data_store = tracker._data_store

            # Create engagement data for each section
            for (
                section,
                baseline_views,
                current_views,
                baseline_connections,
                current_connections,
                baseline_likes,
                current_likes,
            ) in data:
                change_id = f"{section}_test_001"

                # Save baseline
                baseline_snapshot = EngagementSnapshot(
                    timestamp=datetime(2025, 1, 1, 12, 0, 0),
                    profile_views=baseline_views,
                    connection_requests=baseline_connections,
                    post_engagement={
                        "likes": baseline_likes,
                        "comments": 0,
                        "shares": 0,
                        "impressions": 0,
                    },
                )
                data_store.save_engagement_snapshot(baseline_snapshot, change_id)

                # Save current snapshot
                current_snapshot = EngagementSnapshot(
                    timestamp=datetime(2025, 1, 8, 12, 0, 0),
                    profile_views=current_views,
                    connection_requests=current_connections,
                    post_engagement={
                        "likes": current_likes,
                        "comments": 0,
                        "shares": 0,
                        "impressions": 0,
                    },
                )
                data_store.save_engagement_snapshot(current_snapshot, change_id)

            # Get the ranked sections
            ranked_sections = tracker.get_top_performing_sections()

            # Verify all sections with data are present
            sections_in_data = [d[0] for d in data]
            for section in ranked_sections:
                assert section in sections_in_data

            # Verify ranking is in descending order of improvement
            if len(ranked_sections) >= 2:
                # Compute expected improvements for each section
                section_improvements = {}
                for (
                    section,
                    baseline_views,
                    current_views,
                    baseline_connections,
                    current_connections,
                    baseline_likes,
                    current_likes,
                ) in data:
                    improvements = []
                    # profile_views improvement
                    if baseline_views > 0:
                        improvements.append(
                            ((current_views - baseline_views) / baseline_views) * 100.0
                        )
                    else:
                        improvements.append(0.0)
                    # connection_requests improvement
                    if baseline_connections > 0:
                        improvements.append(
                            ((current_connections - baseline_connections) / baseline_connections) * 100.0
                        )
                    else:
                        improvements.append(0.0)
                    # post_likes improvement
                    if baseline_likes > 0:
                        improvements.append(
                            ((current_likes - baseline_likes) / baseline_likes) * 100.0
                        )
                    else:
                        improvements.append(0.0)
                    # comments, shares, impressions are all 0 baseline -> 0% change
                    improvements.extend([0.0, 0.0, 0.0])

                    avg_improvement = sum(improvements) / len(improvements)
                    section_improvements[section] = avg_improvement

                # Verify descending order
                for i in range(len(ranked_sections) - 1):
                    curr_section = ranked_sections[i]
                    next_section = ranked_sections[i + 1]
                    assert section_improvements[curr_section] >= section_improvements[next_section], (
                        f"Section '{curr_section}' (improvement={section_improvements[curr_section]:.2f}) "
                        f"should rank above '{next_section}' (improvement={section_improvements[next_section]:.2f})"
                    )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @given(
        section=st.sampled_from(SECTION_NAMES),
        baseline_views=st.integers(min_value=1, max_value=1000),
        current_views=st.integers(min_value=1, max_value=5000),
        baseline_connections=st.integers(min_value=1, max_value=500),
        current_connections=st.integers(min_value=1, max_value=2000),
    )
    @settings(max_examples=30, deadline=None)
    def test_single_section_appears_in_ranking(
        self,
        section: str,
        baseline_views: int,
        current_views: int,
        baseline_connections: int,
        current_connections: int,
    ):
        """A section with engagement history appears in the ranking."""
        tmp_dir = tempfile.mkdtemp()
        try:
            tracker = _create_tracker_with_real_store(tmp_dir)
            data_store = tracker._data_store

            change_id = f"{section}_test_001"

            baseline_snapshot = EngagementSnapshot(
                timestamp=datetime(2025, 1, 1, 12, 0, 0),
                profile_views=baseline_views,
                connection_requests=baseline_connections,
                post_engagement={"likes": 0, "comments": 0, "shares": 0, "impressions": 0},
            )
            data_store.save_engagement_snapshot(baseline_snapshot, change_id)

            current_snapshot = EngagementSnapshot(
                timestamp=datetime(2025, 1, 8, 12, 0, 0),
                profile_views=current_views,
                connection_requests=current_connections,
                post_engagement={"likes": 0, "comments": 0, "shares": 0, "impressions": 0},
            )
            data_store.save_engagement_snapshot(current_snapshot, change_id)

            ranked_sections = tracker.get_top_performing_sections()

            assert section in ranked_sections, (
                f"Section '{section}' with engagement data should appear in ranking"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_empty_engagement_returns_empty_ranking(self):
        """When no engagement data exists, ranking is empty."""
        tmp_dir = tempfile.mkdtemp()
        try:
            tracker = _create_tracker_with_real_store(tmp_dir)
            ranked_sections = tracker.get_top_performing_sections()
            assert ranked_sections == []
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_baseline_only_excluded_from_ranking(self):
        """Sections with only a baseline (no followup snapshot) are excluded."""
        tmp_dir = tempfile.mkdtemp()
        try:
            tracker = _create_tracker_with_real_store(tmp_dir)
            data_store = tracker._data_store

            change_id = "headline_test_001"

            baseline_snapshot = EngagementSnapshot(
                timestamp=datetime(2025, 1, 1, 12, 0, 0),
                profile_views=100,
                connection_requests=50,
                post_engagement={"likes": 10, "comments": 5, "shares": 2, "impressions": 500},
            )
            data_store.save_engagement_snapshot(baseline_snapshot, change_id)

            ranked_sections = tracker.get_top_performing_sections()
            assert ranked_sections == [], (
                "Sections with only a baseline should not appear in ranking"
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
