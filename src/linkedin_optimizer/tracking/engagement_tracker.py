"""Engagement tracking for measuring optimization impact over time.

This module provides the EngagementTracker class that records baseline metrics
when changes are applied, collects periodic snapshots, generates comparison
reports, and identifies top-performing sections.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from linkedin_optimizer.models import (
    EngagementComparison,
    EngagementReport,
    EngagementSnapshot,
)
from linkedin_optimizer.persistence import DataStore
from linkedin_optimizer.scrapers import LinkedInMCPClient

logger = logging.getLogger(__name__)


class EngagementTracker:
    """Tracks engagement metrics after profile changes are applied.

    Records baseline snapshots at the time of change application, collects
    periodic metrics, generates comparison reports, and ranks sections by
    historical performance improvement.
    """

    def __init__(self, mcp_client: LinkedInMCPClient, data_store: DataStore) -> None:
        """Initialize the EngagementTracker.

        Args:
            mcp_client: LinkedIn MCP client for fetching profile metrics.
            data_store: Persistence layer for saving/loading engagement data.
        """
        self._mcp_client = mcp_client
        self._data_store = data_store

    async def _fetch_current_metrics(self) -> EngagementSnapshot:
        """Fetch current engagement metrics from LinkedIn via MCP.

        Retrieves profile views, connection requests, and post engagement
        data from the authenticated user's profile.

        Returns:
            An EngagementSnapshot with current metric values.

        Raises:
            Exception: If MCP calls fail (callers handle retries).
        """
        # Get profile data for views and connection count
        profile_data = await self._mcp_client.get_my_profile()

        profile_views = 0
        connection_requests = 0

        if isinstance(profile_data, dict):
            profile_views = profile_data.get("profile_views", 0) or 0
            connection_requests = profile_data.get("connection_requests", 0) or 0

        # Get feed/post engagement data
        post_engagement = {"likes": 0, "comments": 0, "shares": 0, "impressions": 0}
        try:
            feed_data = await self._mcp_client.get_feed(count=10)
            if isinstance(feed_data, list):
                total_likes = 0
                total_comments = 0
                total_shares = 0
                total_impressions = 0
                for post in feed_data:
                    if isinstance(post, dict):
                        total_likes += post.get("reactions", 0) or post.get("likes", 0) or 0
                        total_comments += post.get("comments", 0) or 0
                        total_shares += post.get("shares", 0) or 0
                        total_impressions += post.get("impressions", 0) or 0
                post_engagement = {
                    "likes": total_likes,
                    "comments": total_comments,
                    "shares": total_shares,
                    "impressions": total_impressions,
                }
        except Exception as e:
            logger.warning("Failed to fetch feed data for engagement: %s", e)

        return EngagementSnapshot(
            timestamp=datetime.now(),
            profile_views=profile_views,
            connection_requests=connection_requests,
            post_engagement=post_engagement,
        )

    async def record_baseline(self, change_id: str, section_name: str) -> EngagementSnapshot:
        """Record baseline metrics when a change is applied.

        Snapshots profile_views, connection_requests, and post engagement
        at the time of change application.

        Args:
            change_id: Unique identifier for the change being tracked.
            section_name: The profile section that was changed.

        Returns:
            The recorded EngagementSnapshot.
        """
        logger.info(
            "Recording baseline engagement for change '%s' (section: %s)",
            change_id,
            section_name,
        )

        snapshot = await self._fetch_current_metrics()

        # Save the baseline snapshot via data_store
        # The DataStore's save_engagement_snapshot saves as baseline if none exists
        self._data_store.save_engagement_snapshot(snapshot, change_id)

        logger.info(
            "Baseline recorded: views=%d, connections=%d, engagement=%s",
            snapshot.profile_views,
            snapshot.connection_requests,
            snapshot.post_engagement,
        )

        return snapshot

    async def collect_metrics(self, change_id: str) -> EngagementSnapshot:
        """Collect current engagement metrics as a periodic snapshot.

        Similar to record_baseline but saves as a periodic snapshot rather
        than the baseline.

        Args:
            change_id: Identifier for the change being tracked.

        Returns:
            The collected EngagementSnapshot.
        """
        logger.info("Collecting periodic metrics for change '%s'", change_id)

        snapshot = await self._fetch_current_metrics()

        # Save as periodic snapshot (DataStore handles baseline vs snapshot logic)
        self._data_store.save_engagement_snapshot(snapshot, change_id)

        logger.info(
            "Metrics collected: views=%d, connections=%d, engagement=%s",
            snapshot.profile_views,
            snapshot.connection_requests,
            snapshot.post_engagement,
        )

        return snapshot

    async def generate_comparison_report(
        self, change_id: str, days_elapsed: int = 7
    ) -> Optional[EngagementReport]:
        """Generate a comparison report for a tracked change.

        Computes absolute and percentage changes for each metric between
        the baseline and the latest snapshot.

        Args:
            change_id: Identifier for the change being tracked.
            days_elapsed: Number of days since the change was applied (default: 7).

        Returns:
            An EngagementReport with comparison data, or None if baseline
            or snapshots are not available.
        """
        logger.info(
            "Generating comparison report for change '%s' (days=%d)",
            change_id,
            days_elapsed,
        )

        history = self._data_store.load_engagement_history(change_id)

        if not history:
            logger.warning("No engagement history found for change '%s'", change_id)
            return None

        baseline = history[0]

        # Use the latest snapshot for comparison
        if len(history) > 1:
            latest = history[-1]
        else:
            # Only baseline exists, no comparison possible yet
            logger.info("Only baseline exists for change '%s', no comparison yet", change_id)
            return None

        # Compute comparisons for each metric
        comparisons: list[EngagementComparison] = []

        # Profile views
        comparisons.append(
            self._compute_comparison(
                "profile_views",
                float(baseline.profile_views),
                float(latest.profile_views),
            )
        )

        # Connection requests
        comparisons.append(
            self._compute_comparison(
                "connection_requests",
                float(baseline.connection_requests),
                float(latest.connection_requests),
            )
        )

        # Post engagement metrics
        baseline_engagement = baseline.post_engagement or {}
        latest_engagement = latest.post_engagement or {}

        for metric_key in ["likes", "comments", "shares", "impressions"]:
            baseline_val = float(baseline_engagement.get(metric_key, 0))
            current_val = float(latest_engagement.get(metric_key, 0))
            comparisons.append(
                self._compute_comparison(
                    f"post_{metric_key}",
                    baseline_val,
                    current_val,
                )
            )

        # Determine overall trend
        overall_trend = self._determine_trend(comparisons)

        # Derive section_name from the stored data
        # The section_name is stored at record_baseline time; we'll use change_id prefix
        # or load from metadata. For now, extract from change_id convention.
        section_name = self._extract_section_name(change_id)

        report = EngagementReport(
            change_id=change_id,
            section_name=section_name,
            applied_at=baseline.timestamp,
            days_elapsed=days_elapsed,
            comparisons=comparisons,
            overall_trend=overall_trend,
        )

        logger.info(
            "Comparison report generated for '%s': trend=%s",
            change_id,
            overall_trend,
        )

        return report

    def get_top_performing_sections(self) -> list[str]:
        """Return sections ranked by historical optimization impact (descending).

        Loads all engagement data and ranks sections by the average metric
        improvement across all tracked changes.

        Returns:
            List of section names sorted by descending improvement.
        """
        logger.info("Computing top performing sections")

        # Scan all engagement directories for tracked changes
        engagement_dir = self._data_store.data_dir / "engagement"
        if not engagement_dir.exists():
            return []

        section_improvements: dict[str, list[float]] = {}

        for change_dir in engagement_dir.iterdir():
            if not change_dir.is_dir():
                continue

            change_id = change_dir.name
            history = self._data_store.load_engagement_history(change_id)

            if len(history) < 2:
                continue

            baseline = history[0]
            latest = history[-1]

            # Calculate total improvement percentage across all metrics
            total_improvement = 0.0
            metric_count = 0

            # Profile views improvement
            improvement = self._calc_percentage_change(
                float(baseline.profile_views), float(latest.profile_views)
            )
            total_improvement += improvement
            metric_count += 1

            # Connection requests improvement
            improvement = self._calc_percentage_change(
                float(baseline.connection_requests), float(latest.connection_requests)
            )
            total_improvement += improvement
            metric_count += 1

            # Post engagement improvements
            baseline_engagement = baseline.post_engagement or {}
            latest_engagement = latest.post_engagement or {}
            for key in ["likes", "comments", "shares", "impressions"]:
                b_val = float(baseline_engagement.get(key, 0))
                c_val = float(latest_engagement.get(key, 0))
                improvement = self._calc_percentage_change(b_val, c_val)
                total_improvement += improvement
                metric_count += 1

            avg_improvement = total_improvement / metric_count if metric_count > 0 else 0.0

            section_name = self._extract_section_name(change_id)
            if section_name not in section_improvements:
                section_improvements[section_name] = []
            section_improvements[section_name].append(avg_improvement)

        # Rank sections by average improvement (descending)
        section_avg: dict[str, float] = {}
        for section, improvements in section_improvements.items():
            section_avg[section] = sum(improvements) / len(improvements) if improvements else 0.0

        ranked = sorted(section_avg.keys(), key=lambda s: section_avg[s], reverse=True)

        logger.info("Top performing sections: %s", ranked)
        return ranked

    async def retry_collection(self, change_id: str, max_retries: int = 3) -> bool:
        """Retry metric collection over 6 hours if metrics are unavailable.

        Waits 2 hours between retry attempts and logs data gaps.

        Args:
            change_id: Identifier for the change being tracked.
            max_retries: Maximum number of retry attempts (default: 3).

        Returns:
            True if metrics were successfully collected, False otherwise.
        """
        logger.info(
            "Starting retry collection for change '%s' (max_retries=%d)",
            change_id,
            max_retries,
        )

        # Retry interval: 6 hours / 3 retries = 2 hours between attempts
        retry_interval_seconds = 2 * 60 * 60  # 2 hours

        for attempt in range(1, max_retries + 1):
            try:
                await self.collect_metrics(change_id)
                logger.info(
                    "Retry collection succeeded for '%s' on attempt %d",
                    change_id,
                    attempt,
                )
                return True
            except Exception as e:
                logger.warning(
                    "Retry attempt %d/%d failed for change '%s': %s",
                    attempt,
                    max_retries,
                    change_id,
                    e,
                )
                # Log the data gap
                logger.info(
                    "Data gap logged for change '%s' at %s (attempt %d/%d)",
                    change_id,
                    datetime.now().isoformat(),
                    attempt,
                    max_retries,
                )

                if attempt < max_retries:
                    logger.info(
                        "Waiting %d seconds before retry attempt %d",
                        retry_interval_seconds,
                        attempt + 1,
                    )
                    await asyncio.sleep(retry_interval_seconds)

        logger.error(
            "All retry attempts exhausted for change '%s'. Data gap recorded.",
            change_id,
        )
        return False

    # --- Private Helpers ---

    def _compute_comparison(
        self, metric_name: str, baseline_value: float, current_value: float
    ) -> EngagementComparison:
        """Compute an EngagementComparison for a single metric.

        Args:
            metric_name: Name of the metric.
            baseline_value: The baseline measurement.
            current_value: The current measurement.

        Returns:
            An EngagementComparison with absolute and percentage changes.
        """
        absolute_change = current_value - baseline_value
        percentage_change = self._calc_percentage_change(baseline_value, current_value)

        return EngagementComparison(
            metric_name=metric_name,
            baseline_value=baseline_value,
            current_value=current_value,
            absolute_change=absolute_change,
            percentage_change=percentage_change,
        )

    @staticmethod
    def _calc_percentage_change(baseline: float, current: float) -> float:
        """Calculate percentage change, returning 0.0 when baseline is zero.

        Args:
            baseline: The baseline value.
            current: The current value.

        Returns:
            Percentage change, or 0.0 if baseline is zero.
        """
        if baseline > 0:
            return ((current - baseline) / baseline) * 100.0
        return 0.0

    @staticmethod
    def _determine_trend(comparisons: list[EngagementComparison]) -> str:
        """Determine overall trend from a list of metric comparisons.

        Args:
            comparisons: List of EngagementComparison objects.

        Returns:
            "improving" if majority positive, "declining" if majority negative,
            "stable" otherwise.
        """
        if not comparisons:
            return "stable"

        positive = sum(1 for c in comparisons if c.absolute_change > 0)
        negative = sum(1 for c in comparisons if c.absolute_change < 0)
        total = len(comparisons)

        if positive > total / 2:
            return "improving"
        elif negative > total / 2:
            return "declining"
        else:
            return "stable"

    @staticmethod
    def _extract_section_name(change_id: str) -> str:
        """Extract section name from a change_id.

        Convention: change_id format is typically "{section}_{timestamp}" or similar.
        Falls back to using the full change_id if no pattern is detected.

        Args:
            change_id: The change identifier.

        Returns:
            The extracted section name.
        """
        # Try to extract section name from common patterns
        # e.g., "headline_20250115_143022" -> "headline"
        # e.g., "about_change_001" -> "about"
        parts = change_id.split("_")
        if parts:
            # Return the first part as the section name
            return parts[0]
        return change_id
