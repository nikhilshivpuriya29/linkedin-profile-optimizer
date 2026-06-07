"""Unit tests for the DataStore persistence layer."""

import json
from datetime import datetime, timedelta

import pytest

from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalSession,
    ApprovalStatus,
    ContentPackage,
    EngagementSnapshot,
    HeadlineSuggestion,
    OptimizationReport,
    PipelineStatus,
    PostIdea,
    ProfileData,
    RunMetadata,
    SectionScore,
    FactorScore,
    SectionInsight,
    Recommendation,
    Priority,
)
from linkedin_optimizer.persistence.data_store import DataStore


@pytest.fixture
def store(tmp_path):
    """Create a DataStore instance with a temp directory."""
    return DataStore(str(tmp_path / "data"))


@pytest.fixture
def sample_profile():
    """Create a sample ProfileData for testing."""
    return ProfileData(
        headline="Senior Engineer | Python Expert",
        about="Building scalable systems for 10+ years.",
        experience=[{"title": "Senior Engineer", "company": "Acme Inc"}],
        skills=[{"name": "Python", "endorsements": 50}],
        endorsements=[{"skill": "Python", "count": 50}],
        posts=[{"text": "Excited about AI!", "likes": 42}],
        follower_count=1200,
        connection_count=500,
        profile_views=300,
    )


@pytest.fixture
def sample_report():
    """Create a sample OptimizationReport for testing."""
    return OptimizationReport(
        sections=[
            SectionScore(
                section_name="headline",
                overall_score=75,
                factor_scores=[
                    FactorScore(factor_name="keywords", score=80, explanation="Good keywords")
                ],
            )
        ],
        insights=[
            SectionInsight(
                section_name="headline",
                strengths=["Clear value proposition"],
                weaknesses=["Could use more keywords"],
                recommendations=[
                    Recommendation(
                        element="headline",
                        modification="Add industry keywords",
                        priority=Priority.HIGH,
                        guideline_reference="LinkedIn best practices",
                        expected_impact="Better search visibility",
                    )
                ],
            )
        ],
        overall_score=75,
        generated_at="2024-01-15T10:00:00",
    )


@pytest.fixture
def sample_content_package():
    """Create a sample ContentPackage for testing."""
    return ContentPackage(
        headline=HeadlineSuggestion(
            text="Senior Python Engineer | Cloud Architecture",
            keywords_used=["Python", "Cloud"],
            value_proposition="Building scalable systems",
        ),
        post_ideas=[
            PostIdea(topic="AI in Production", format="text", content_outline="Discuss best practices for deploying ML models."),
        ],
        generated_at="2024-01-15T10:30:00",
    )


@pytest.fixture
def sample_approval_session():
    """Create a sample ApprovalSession for testing."""
    now = datetime.now()
    return ApprovalSession(
        session_id="sess-001",
        run_id="run-abc",
        items=[
            ApprovalItem(
                item_id="item-1",
                section_name="headline",
                current_content="Old headline",
                proposed_content="New headline",
                status=ApprovalStatus.PENDING,
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
        ],
        created_at=now,
        notification_sent=False,
    )


@pytest.fixture
def sample_run_metadata():
    """Create a sample RunMetadata for testing."""
    now = datetime.now()
    return RunMetadata(
        run_id="run-abc",
        start_time=now,
        end_time=now + timedelta(minutes=5),
        status=PipelineStatus.COMPLETED,
        summary="Completed successfully",
        error=None,
    )


@pytest.fixture
def sample_engagement_snapshot():
    """Create a sample EngagementSnapshot for testing."""
    return EngagementSnapshot(
        timestamp=datetime.now(),
        profile_views=100,
        connection_requests=15,
        post_engagement={"likes": 50, "comments": 10, "shares": 5},
    )


# --- Directory Structure Tests ---


class TestDirectoryStructure:
    """Test that DataStore creates the correct directory structure."""

    def test_creates_root_directory(self, tmp_path):
        data_dir = tmp_path / "mydata"
        DataStore(str(data_dir))
        assert data_dir.exists()

    def test_creates_all_subdirectories(self, tmp_path):
        data_dir = tmp_path / "mydata"
        DataStore(str(data_dir))
        for subdir in DataStore.SUBDIRS:
            assert (data_dir / subdir).exists()

    def test_idempotent_creation(self, tmp_path):
        """Creating DataStore twice should not raise errors."""
        data_dir = tmp_path / "mydata"
        DataStore(str(data_dir))
        DataStore(str(data_dir))  # Should not fail


# --- Save/Load Round-Trip Tests ---


class TestProfileSnapshotRoundTrip:
    """Test save and verify for profile snapshots."""

    def test_save_creates_file_in_profiles_dir(self, store, sample_profile, tmp_path):
        result = store.save_profile_snapshot(sample_profile, "run-001")
        assert result != ""
        assert "profiles" in result
        assert "run-001_profile.json" in result

    def test_save_file_contains_valid_json(self, store, sample_profile, tmp_path):
        result = store.save_profile_snapshot(sample_profile, "run-002")
        with open(result, "r") as f:
            data = json.load(f)
        assert data["headline"] == "Senior Engineer | Python Expert"
        assert data["follower_count"] == 1200


class TestOptimizationReportRoundTrip:
    """Test save/load round-trip for optimization reports."""

    def test_save_creates_file_in_reports_dir(self, store, sample_report):
        result = store.save_optimization_report(sample_report, "run-001")
        assert result != ""
        assert "reports" in result
        assert "run-001_report.json" in result

    def test_load_latest_report(self, store, sample_report):
        store.save_optimization_report(sample_report, "run-001")
        loaded = store.load_latest_report()
        assert loaded is not None
        assert loaded.overall_score == 75
        assert len(loaded.sections) == 1
        assert loaded.sections[0].section_name == "headline"

    def test_load_latest_returns_most_recent(self, store, sample_report):
        store.save_optimization_report(sample_report, "run-001")
        second_report = OptimizationReport(
            sections=[], insights=[], overall_score=90, generated_at="2024-02-01T10:00:00"
        )
        store.save_optimization_report(second_report, "run-002")
        loaded = store.load_latest_report()
        assert loaded is not None
        # The latest by sorted filename will be run-002
        assert loaded.overall_score == 90


class TestContentPackageRoundTrip:
    """Test save for content packages."""

    def test_save_creates_file_in_content_dir(self, store, sample_content_package):
        result = store.save_content_package(sample_content_package, "run-001")
        assert result != ""
        assert "content" in result
        assert "run-001_content.json" in result

    def test_saved_content_is_valid(self, store, sample_content_package):
        result = store.save_content_package(sample_content_package, "run-003")
        with open(result, "r") as f:
            data = json.load(f)
        assert data["headline"]["text"] == "Senior Python Engineer | Cloud Architecture"
        assert len(data["post_ideas"]) == 1


class TestApprovalSessionRoundTrip:
    """Test save/load round-trip for approval sessions."""

    def test_save_creates_file_in_approvals_dir(self, store, sample_approval_session):
        result = store.save_approval_session(sample_approval_session)
        assert result != ""
        assert "approvals" in result
        assert "sess-001_approval.json" in result

    def test_load_approval_session(self, store, sample_approval_session):
        store.save_approval_session(sample_approval_session)
        loaded = store.load_approval_session("sess-001")
        assert loaded is not None
        assert loaded.session_id == "sess-001"
        assert loaded.run_id == "run-abc"
        assert len(loaded.items) == 1
        assert loaded.items[0].section_name == "headline"
        assert loaded.items[0].status == ApprovalStatus.PENDING

    def test_load_nonexistent_session_returns_none(self, store):
        result = store.load_approval_session("nonexistent")
        assert result is None


class TestRunMetadataRoundTrip:
    """Test save/load round-trip for run metadata."""

    def test_save_creates_file_in_runs_dir(self, store, sample_run_metadata):
        result = store.save_run_metadata(sample_run_metadata)
        assert result != ""
        assert "runs" in result
        assert "run-abc_meta.json" in result

    def test_get_run_history(self, store):
        now = datetime.now()
        for i in range(5):
            meta = RunMetadata(
                run_id=f"run-{i:03d}",
                start_time=now + timedelta(hours=i),
                end_time=now + timedelta(hours=i, minutes=5),
                status=PipelineStatus.COMPLETED,
                summary=f"Run {i}",
                error=None,
            )
            store.save_run_metadata(meta)

        history = store.get_run_history(limit=3)
        assert len(history) == 3
        # Should be sorted most recent first (by filename)
        assert history[0].run_id == "run-004"

    def test_get_run_history_empty(self, store):
        history = store.get_run_history()
        assert history == []


class TestEngagementSnapshotRoundTrip:
    """Test save/load round-trip for engagement snapshots."""

    def test_save_baseline_creates_file(self, store, sample_engagement_snapshot):
        result = store.save_engagement_snapshot(sample_engagement_snapshot, "change-001")
        assert result != ""
        assert "engagement" in result
        assert "change-001" in result
        assert "baseline.json" in result

    def test_second_save_goes_to_snapshots(self, store, sample_engagement_snapshot):
        # First save is baseline
        store.save_engagement_snapshot(sample_engagement_snapshot, "change-001")
        # Second save goes to snapshots dir
        second = EngagementSnapshot(
            timestamp=datetime.now() + timedelta(days=1),
            profile_views=120,
            connection_requests=20,
            post_engagement={"likes": 60, "comments": 15, "shares": 8},
        )
        result = store.save_engagement_snapshot(second, "change-001")
        assert "snapshots" in result

    def test_load_engagement_history(self, store, sample_engagement_snapshot):
        store.save_engagement_snapshot(sample_engagement_snapshot, "change-001")
        second = EngagementSnapshot(
            timestamp=datetime.now() + timedelta(days=1),
            profile_views=120,
            connection_requests=20,
            post_engagement={"likes": 60, "comments": 15, "shares": 8},
        )
        store.save_engagement_snapshot(second, "change-001")

        history = store.load_engagement_history("change-001")
        assert len(history) == 2
        assert history[0].profile_views == 100  # baseline
        assert history[1].profile_views == 120  # snapshot

    def test_load_engagement_history_no_data(self, store):
        history = store.load_engagement_history("nonexistent")
        assert history == []


# --- Error Handling Tests ---


class TestMissingFiles:
    """Test graceful handling when files don't exist."""

    def test_load_approval_session_missing(self, store):
        result = store.load_approval_session("does-not-exist")
        assert result is None

    def test_load_latest_report_no_reports(self, store):
        result = store.load_latest_report()
        assert result is None

    def test_get_run_history_no_runs(self, store):
        result = store.get_run_history()
        assert result == []

    def test_load_engagement_history_missing_change(self, store):
        result = store.load_engagement_history("no-such-change")
        assert result == []


class TestCorruptedJson:
    """Test graceful handling of corrupted JSON files."""

    def test_corrupted_approval_session(self, store, tmp_path):
        # Write corrupted JSON to the approvals directory
        data_dir = tmp_path / "data"
        approvals_dir = data_dir / "approvals"
        corrupted_file = approvals_dir / "bad-session_approval.json"
        corrupted_file.write_text("not valid json {{{")

        result = store.load_approval_session("bad-session")
        assert result is None

    def test_corrupted_report_file(self, store, tmp_path):
        # Write corrupted JSON to reports directory
        data_dir = tmp_path / "data"
        reports_dir = data_dir / "reports"
        corrupted_file = reports_dir / "run-bad_report.json"
        corrupted_file.write_text("{invalid json content")

        result = store.load_latest_report()
        assert result is None

    def test_corrupted_run_metadata(self, store, tmp_path):
        # Write corrupted JSON to runs directory
        data_dir = tmp_path / "data"
        runs_dir = data_dir / "runs"
        corrupted_file = runs_dir / "run-bad_meta.json"
        corrupted_file.write_text("[[broken")

        result = store.get_run_history()
        assert result == []

    def test_corrupted_engagement_baseline(self, store, tmp_path):
        # Write corrupted JSON to engagement directory
        data_dir = tmp_path / "data"
        change_dir = data_dir / "engagement" / "corrupt-change"
        change_dir.mkdir(parents=True)
        (change_dir / "snapshots").mkdir()
        baseline = change_dir / "baseline.json"
        baseline.write_text("totally broken")

        result = store.load_engagement_history("corrupt-change")
        assert result == []

    def test_partially_corrupted_run_history(self, store, tmp_path):
        """If one file is corrupted, others should still load."""
        now = datetime.now()
        # Save a valid run
        valid_meta = RunMetadata(
            run_id="run-good",
            start_time=now,
            end_time=now + timedelta(minutes=5),
            status=PipelineStatus.COMPLETED,
            summary="Good run",
            error=None,
        )
        store.save_run_metadata(valid_meta)

        # Write a corrupted file
        data_dir = tmp_path / "data"
        runs_dir = data_dir / "runs"
        corrupted_file = runs_dir / "run-zzz_meta.json"
        corrupted_file.write_text("not json")

        # Should still load the valid one, skipping the corrupted one
        history = store.get_run_history()
        assert len(history) == 1
        assert history[0].run_id == "run-good"
