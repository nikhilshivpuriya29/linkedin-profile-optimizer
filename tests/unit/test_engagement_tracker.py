"""Unit tests for the EngagementTracker module."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from linkedin_optimizer.models import (
    EngagementComparison,
    EngagementReport,
    EngagementSnapshot,
)
from linkedin_optimizer.persistence.data_store import DataStore
from linkedin_optimizer.scrapers import LinkedInMCPClient
from linkedin_optimizer.tracking.engagement_tracker import EngagementTracker


@pytest.fixture
def mock_mcp_client():
    """Create a mocked LinkedInMCPClient."""
    client = AsyncMock(spec=LinkedInMCPClient)
    client.get_my_profile.return_value = {
        "profile_views": 150,
        "connection_requests": 12,
    }
    client.get_feed.return_value = [
        {"reactions": 30, "comments": 5, "shares": 2, "impressions": 500},
        {"reactions": 20, "comments": 3, "shares": 1, "impressions": 300},
    ]
    return client


@pytest.fixture
def data_store(tmp_path):
    """Create a DataStore with a temp directory."""
    return DataStore(str(tmp_path / "data"))


@pytest.fixture
def tracker(mock_mcp_client, data_store):
    """Create an EngagementTracker with mocked dependencies."""
    return EngagementTracker(mock_mcp_client, data_store)


class TestRecordBaseline:
    """Tests for record_baseline method."""

    @pytest.mark.asyncio
    async def test_records_baseline_snapshot(self, tracker, mock_mcp_client, data_store):
        """Test that record_baseline creates and saves a baseline snapshot."""
        snapshot = await tracker.record_baseline("headline_001", "headline")

        assert snapshot.profile_views == 150
        assert snapshot.connection_requests == 12
        assert snapshot.post_engagement["likes"] == 50  # 30 + 20
        assert snapshot.post_engagement["comments"] == 8  # 5 + 3
        assert snapshot.post_engagement["shares"] == 3  # 2 + 1
        assert snapshot.post_engagement["impressions"] == 800  # 500 + 300
        assert isinstance(snapshot.timestamp, datetime)

        # Verify it was saved
        history = data_store.load_engagement_history("headline_001")
        assert len(history) == 1
        assert history[0].profile_views == 150

    @pytest.mark.asyncio
    async def test_calls_mcp_methods(self, tracker, mock_mcp_client):
        """Test that record_baseline calls the MCP client methods."""
        await tracker.record_baseline("about_001", "about")

        mock_mcp_client.get_my_profile.assert_called_once()
        mock_mcp_client.get_feed.assert_called_once_with(count=10)

    @pytest.mark.asyncio
    async def test_handles_missing_profile_views(self, tracker, mock_mcp_client):
        """Test handling when profile_views is missing from response."""
        mock_mcp_client.get_my_profile.return_value = {}

        snapshot = await tracker.record_baseline("test_001", "headline")

        assert snapshot.profile_views == 0
        assert snapshot.connection_requests == 0

    @pytest.mark.asyncio
    async def test_handles_feed_failure(self, tracker, mock_mcp_client):
        """Test handling when feed data retrieval fails."""
        mock_mcp_client.get_feed.side_effect = Exception("Feed unavailable")

        snapshot = await tracker.record_baseline("test_002", "headline")

        # Should still succeed with zero post engagement
        assert snapshot.profile_views == 150
        assert snapshot.post_engagement == {
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "impressions": 0,
        }


class TestCollectMetrics:
    """Tests for collect_metrics method."""

    @pytest.mark.asyncio
    async def test_collects_periodic_snapshot(self, tracker, data_store):
        """Test that collect_metrics saves a periodic snapshot after baseline."""
        # First record baseline
        await tracker.record_baseline("headline_002", "headline")

        # Then collect metrics
        snapshot = await tracker.collect_metrics("headline_002")

        assert snapshot.profile_views == 150
        assert isinstance(snapshot.timestamp, datetime)

        # Should now have baseline + 1 periodic snapshot
        history = data_store.load_engagement_history("headline_002")
        assert len(history) == 2


class TestGenerateComparisonReport:
    """Tests for generate_comparison_report method."""

    @pytest.mark.asyncio
    async def test_generates_report_with_improvements(self, tracker, mock_mcp_client, data_store):
        """Test report generation when metrics improve."""
        # Record baseline with initial values
        await tracker.record_baseline("headline_003", "headline")

        # Update mock to return improved metrics
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 200,
            "connection_requests": 20,
        }
        mock_mcp_client.get_feed.return_value = [
            {"reactions": 50, "comments": 10, "shares": 5, "impressions": 1000},
        ]

        # Collect improved metrics
        await tracker.collect_metrics("headline_003")

        # Generate report
        report = await tracker.generate_comparison_report("headline_003", days_elapsed=7)

        assert report is not None
        assert report.change_id == "headline_003"
        assert report.days_elapsed == 7
        assert report.overall_trend == "improving"

        # Check that comparisons are correct
        views_comparison = next(c for c in report.comparisons if c.metric_name == "profile_views")
        assert views_comparison.baseline_value == 150.0
        assert views_comparison.current_value == 200.0
        assert views_comparison.absolute_change == 50.0
        assert views_comparison.percentage_change == pytest.approx((50.0 / 150.0) * 100.0)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_history(self, tracker):
        """Test that report returns None when no data exists."""
        report = await tracker.generate_comparison_report("nonexistent", days_elapsed=7)
        assert report is None

    @pytest.mark.asyncio
    async def test_returns_none_when_only_baseline(self, tracker):
        """Test that report returns None when only baseline exists."""
        await tracker.record_baseline("only_baseline", "headline")

        report = await tracker.generate_comparison_report("only_baseline", days_elapsed=7)
        assert report is None

    @pytest.mark.asyncio
    async def test_percentage_change_zero_when_baseline_zero(self, tracker, mock_mcp_client, data_store):
        """Test that percentage_change is 0.0 when baseline is zero."""
        # Set baseline with zero metrics
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 0,
            "connection_requests": 0,
        }
        mock_mcp_client.get_feed.return_value = []
        await tracker.record_baseline("zero_baseline", "headline")

        # Now set some values for collection
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 50,
            "connection_requests": 5,
        }
        await tracker.collect_metrics("zero_baseline")

        report = await tracker.generate_comparison_report("zero_baseline", days_elapsed=7)

        assert report is not None
        views_comparison = next(c for c in report.comparisons if c.metric_name == "profile_views")
        assert views_comparison.percentage_change == 0.0
        assert views_comparison.absolute_change == 50.0

    @pytest.mark.asyncio
    async def test_declining_trend(self, tracker, mock_mcp_client):
        """Test detection of declining trend."""
        # Good baseline
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 200,
            "connection_requests": 20,
        }
        mock_mcp_client.get_feed.return_value = [
            {"reactions": 50, "comments": 10, "shares": 5, "impressions": 1000},
        ]
        await tracker.record_baseline("declining_test", "headline")

        # Worse current metrics
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 100,
            "connection_requests": 10,
        }
        mock_mcp_client.get_feed.return_value = [
            {"reactions": 20, "comments": 3, "shares": 1, "impressions": 400},
        ]
        await tracker.collect_metrics("declining_test")

        report = await tracker.generate_comparison_report("declining_test", days_elapsed=7)

        assert report is not None
        assert report.overall_trend == "declining"


class TestGetTopPerformingSections:
    """Tests for get_top_performing_sections method."""

    @pytest.mark.asyncio
    async def test_ranks_sections_by_improvement(self, tracker, mock_mcp_client, data_store):
        """Test that sections are ranked by improvement descending."""
        # Track headline change with moderate improvement
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 100,
            "connection_requests": 10,
        }
        mock_mcp_client.get_feed.return_value = []
        await tracker.record_baseline("headline_rank", "headline")

        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 150,
            "connection_requests": 15,
        }
        await tracker.collect_metrics("headline_rank")

        # Track about change with higher improvement
        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 100,
            "connection_requests": 10,
        }
        mock_mcp_client.get_feed.return_value = []
        await tracker.record_baseline("about_rank", "about")

        mock_mcp_client.get_my_profile.return_value = {
            "profile_views": 300,
            "connection_requests": 30,
        }
        await tracker.collect_metrics("about_rank")

        # Get rankings
        ranked = tracker.get_top_performing_sections()

        assert "about" in ranked
        assert "headline" in ranked
        assert ranked.index("about") < ranked.index("headline")

    def test_empty_when_no_data(self, tracker):
        """Test returns empty list when no engagement data exists."""
        result = tracker.get_top_performing_sections()
        assert result == []


class TestRetryCollection:
    """Tests for retry_collection method."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self, tracker, mock_mcp_client):
        """Test successful collection on first retry attempt."""
        # Record baseline first
        await tracker.record_baseline("retry_001", "headline")

        result = await tracker.retry_collection("retry_001", max_retries=3)
        assert result is True

    @pytest.mark.asyncio
    async def test_succeeds_after_failures(self, tracker, mock_mcp_client):
        """Test successful collection after initial failures."""
        await tracker.record_baseline("retry_002", "headline")

        # Make get_my_profile fail twice then succeed
        call_count = 0
        original_return = mock_mcp_client.get_my_profile.return_value

        async def side_effect_fn():
            nonlocal call_count
            call_count += 1
            # First call is baseline (already done), then fail 2 times, then succeed
            if call_count <= 2:
                raise Exception("Temporary failure")
            return original_return

        mock_mcp_client.get_my_profile.side_effect = side_effect_fn

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await tracker.retry_collection("retry_002", max_retries=3)

        assert result is True

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(self, tracker, mock_mcp_client):
        """Test failure when all retries are exhausted."""
        await tracker.record_baseline("retry_003", "headline")

        mock_mcp_client.get_my_profile.side_effect = Exception("Persistent failure")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await tracker.retry_collection("retry_003", max_retries=3)

        assert result is False


class TestHelperMethods:
    """Tests for private helper methods."""

    def test_compute_comparison_positive_change(self, tracker):
        """Test comparison computation with positive change."""
        comparison = tracker._compute_comparison("views", 100.0, 150.0)

        assert comparison.metric_name == "views"
        assert comparison.baseline_value == 100.0
        assert comparison.current_value == 150.0
        assert comparison.absolute_change == 50.0
        assert comparison.percentage_change == 50.0

    def test_compute_comparison_zero_baseline(self, tracker):
        """Test that percentage_change is 0.0 when baseline is zero."""
        comparison = tracker._compute_comparison("views", 0.0, 50.0)

        assert comparison.absolute_change == 50.0
        assert comparison.percentage_change == 0.0

    def test_determine_trend_improving(self, tracker):
        """Test trend determination when majority positive."""
        comparisons = [
            EngagementComparison("a", 10, 20, 10, 100.0),
            EngagementComparison("b", 10, 20, 10, 100.0),
            EngagementComparison("c", 10, 5, -5, -50.0),
        ]
        assert tracker._determine_trend(comparisons) == "improving"

    def test_determine_trend_declining(self, tracker):
        """Test trend determination when majority negative."""
        comparisons = [
            EngagementComparison("a", 20, 10, -10, -50.0),
            EngagementComparison("b", 20, 10, -10, -50.0),
            EngagementComparison("c", 10, 20, 10, 100.0),
        ]
        assert tracker._determine_trend(comparisons) == "declining"

    def test_determine_trend_stable(self, tracker):
        """Test trend determination when balanced."""
        comparisons = [
            EngagementComparison("a", 10, 20, 10, 100.0),
            EngagementComparison("b", 20, 10, -10, -50.0),
        ]
        assert tracker._determine_trend(comparisons) == "stable"

    def test_determine_trend_empty(self, tracker):
        """Test trend determination with empty comparisons."""
        assert tracker._determine_trend([]) == "stable"

    def test_extract_section_name(self, tracker):
        """Test section name extraction from change_id."""
        assert tracker._extract_section_name("headline_001") == "headline"
        assert tracker._extract_section_name("about_change_123") == "about"
        assert tracker._extract_section_name("experience") == "experience"
