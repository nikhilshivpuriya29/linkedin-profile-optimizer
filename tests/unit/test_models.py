"""Unit tests for core data models serialization round-trips."""

import json
from datetime import datetime, timedelta

from linkedin_optimizer.models import (
    ApprovalItem,
    ApprovalSession,
    ApprovalStatus,
    BannerSuggestion,
    ContentPackage,
    EngagementComparison,
    EngagementReport,
    EngagementSnapshot,
    ExperienceSuggestion,
    ExtractionResult,
    FactorScore,
    GitHubContributions,
    GitHubData,
    GitHubExtractionResult,
    GitHubRepo,
    HeadlineSuggestion,
    AboutSuggestion,
    OptimizationReport,
    PipelineStatus,
    PostIdea,
    Priority,
    ProfileData,
    Recommendation,
    RunMetadata,
    ScheduleInterval,
    SectionInsight,
    SectionScore,
)
from linkedin_optimizer.config import HFModelConfig, PipelineConfig


class TestProfileData:
    def test_round_trip_full(self):
        profile = ProfileData(
            headline="Software Engineer",
            about="I build things.",
            experience=[{"title": "SWE", "company": "Acme"}],
            skills=[{"name": "Python", "endorsements": 10}],
            endorsements=[{"skill": "Python", "endorser": "Alice"}],
            posts=[{"text": "Hello world", "reactions": 5}],
            banner_url="https://example.com/banner.png",
            photo_url="https://example.com/photo.png",
            education=[{"school": "MIT"}],
            certifications=[{"name": "AWS SA"}],
            follower_count=1000,
            connection_count=500,
            profile_views=200,
        )
        result = ProfileData.from_dict(profile.to_dict())
        assert result == profile

    def test_round_trip_defaults(self):
        profile = ProfileData()
        result = ProfileData.from_dict(profile.to_dict())
        assert result == profile

    def test_json_serializable(self):
        profile = ProfileData(headline="Test")
        json_str = json.dumps(profile.to_dict())
        restored = ProfileData.from_dict(json.loads(json_str))
        assert restored.headline == "Test"


class TestExtractionResult:
    def test_round_trip_success(self):
        result = ExtractionResult(
            success=True,
            profile_data=ProfileData(headline="Hello"),
            failed_sections=[],
        )
        restored = ExtractionResult.from_dict(result.to_dict())
        assert restored.success is True
        assert restored.profile_data.headline == "Hello"

    def test_round_trip_failure(self):
        result = ExtractionResult(
            success=False,
            profile_data=None,
            failed_sections=["about", "experience"],
            error_message="Profile not found",
        )
        restored = ExtractionResult.from_dict(result.to_dict())
        assert restored == result


class TestGitHubModels:
    def test_github_repo_round_trip(self):
        repo = GitHubRepo(
            name="my-repo",
            description="A cool repo",
            stars=42,
            primary_language="Python",
            is_pinned=True,
            url="https://github.com/user/my-repo",
        )
        assert GitHubRepo.from_dict(repo.to_dict()) == repo

    def test_github_contributions_round_trip(self):
        contrib = GitHubContributions(
            total_commits_12m=500,
            total_prs_12m=30,
            total_issues_12m=10,
            commits_per_week_avg=9.6,
        )
        assert GitHubContributions.from_dict(contrib.to_dict()) == contrib

    def test_github_data_round_trip(self):
        data = GitHubData(
            repos=[GitHubRepo("r1", "desc", 5, "Python")],
            contributions=GitHubContributions(100, 10, 5, 2.0),
            pinned_repos=[GitHubRepo("r1", "desc", 5, "Python", True)],
            languages={"Python": 50000, "JavaScript": 20000},
            notable_repos=[GitHubRepo("r1", "desc", 5, "Python", True)],
        )
        assert GitHubData.from_dict(data.to_dict()) == data

    def test_github_extraction_result_round_trip(self):
        result = GitHubExtractionResult(
            success=True,
            data=GitHubData(repos=[GitHubRepo("r", None, 0, None)]),
            partial=True,
            unavailable_categories=["contributions"],
        )
        assert GitHubExtractionResult.from_dict(result.to_dict()) == result

    def test_github_extraction_result_failure(self):
        result = GitHubExtractionResult(
            success=False,
            data=None,
            error_message="Timeout",
        )
        assert GitHubExtractionResult.from_dict(result.to_dict()) == result


class TestAnalyzerModels:
    def test_factor_score_round_trip(self):
        fs = FactorScore("keyword_presence", 75, "Good keyword usage")
        assert FactorScore.from_dict(fs.to_dict()) == fs

    def test_section_score_round_trip(self):
        ss = SectionScore(
            section_name="headline",
            overall_score=65,
            factor_scores=[FactorScore("keywords", 70, "ok")],
            missing=False,
            excluded_factors=["engagement"],
        )
        assert SectionScore.from_dict(ss.to_dict()) == ss

    def test_recommendation_round_trip(self):
        rec = Recommendation(
            element="headline text",
            modification="Add value proposition",
            priority=Priority.HIGH,
            guideline_reference="LinkedIn search algorithm",
            expected_impact="15% more appearances",
        )
        assert Recommendation.from_dict(rec.to_dict()) == rec

    def test_section_insight_round_trip(self):
        insight = SectionInsight(
            section_name="about",
            strengths=["Good narrative"],
            weaknesses=["No CTA"],
            recommendations=[
                Recommendation("about", "Add CTA", Priority.MEDIUM, "guide", "5%")
            ],
        )
        assert SectionInsight.from_dict(insight.to_dict()) == insight

    def test_optimization_report_round_trip(self):
        report = OptimizationReport(
            sections=[SectionScore("headline", 55, [FactorScore("kw", 60, "ok")])],
            insights=[
                SectionInsight(
                    "headline",
                    ["Has role"],
                    ["No value prop"],
                    [Recommendation("headline", "add vp", Priority.HIGH, "g", "15%")],
                )
            ],
            overall_score=62,
            github_summary="5 notable repos",
            excluded_sections=[],
            generated_at="2025-01-15T14:32:00Z",
        )
        assert OptimizationReport.from_dict(report.to_dict()) == report


class TestContentCreatorModels:
    def test_headline_suggestion_round_trip(self):
        hs = HeadlineSuggestion(
            text="SWE | Building fast systems",
            keywords_used=["SWE", "fast"],
            value_proposition="Building fast systems",
        )
        assert HeadlineSuggestion.from_dict(hs.to_dict()) == hs

    def test_about_suggestion_round_trip(self):
        about = AboutSuggestion(
            text="I build great software.",
            hook_sentence="What if software could be 10x faster?",
            keywords_used=["software", "fast"],
            call_to_action="Connect with me!",
        )
        assert AboutSuggestion.from_dict(about.to_dict()) == about

    def test_experience_suggestion_round_trip(self):
        exp = ExperienceSuggestion(
            role_title="SWE",
            company="Acme",
            bullets=["Led team of 5", "Reduced latency by 40%"],
            metrics_included=True,
            qualitative_note=None,
        )
        assert ExperienceSuggestion.from_dict(exp.to_dict()) == exp

    def test_experience_suggestion_no_metrics(self):
        exp = ExperienceSuggestion(
            role_title="Intern",
            company="Startup",
            bullets=["Helped ship v2"],
            metrics_included=False,
            qualitative_note="Add specific numbers when available",
        )
        assert ExperienceSuggestion.from_dict(exp.to_dict()) == exp

    def test_post_idea_round_trip(self):
        idea = PostIdea(
            topic="CI/CD lessons",
            format="carousel",
            content_outline="Share the journey. Cover key tools.",
        )
        assert PostIdea.from_dict(idea.to_dict()) == idea

    def test_banner_suggestion_round_trip(self):
        banner = BannerSuggestion(
            dimensions="1584x396",
            color_palette=["#0077B5", "#FFFFFF"],
            tagline="Building Faster",
        )
        assert BannerSuggestion.from_dict(banner.to_dict()) == banner

    def test_content_package_round_trip(self):
        pkg = ContentPackage(
            headline=HeadlineSuggestion("h", ["k"], "vp"),
            about=AboutSuggestion("text", "hook", ["k"], "cta"),
            experience=[ExperienceSuggestion("SWE", "Co", ["b1"], True)],
            post_ideas=[PostIdea("topic", "text", "outline here.")],
            banner=BannerSuggestion("1584x396", ["#000"], "tag"),
            generated_at="2025-01-15T14:34:00Z",
        )
        assert ContentPackage.from_dict(pkg.to_dict()) == pkg

    def test_content_package_empty(self):
        pkg = ContentPackage()
        assert ContentPackage.from_dict(pkg.to_dict()) == pkg


class TestApprovalModels:
    def test_approval_item_round_trip(self):
        now = datetime(2025, 1, 15, 14, 34, 0)
        item = ApprovalItem(
            item_id="item_001",
            section_name="headline",
            current_content="Old headline",
            proposed_content="New headline",
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        restored = ApprovalItem.from_dict(item.to_dict())
        assert restored.item_id == item.item_id
        assert restored.status == ApprovalStatus.PENDING
        assert restored.created_at == now
        assert restored.expires_at == now + timedelta(days=7)

    def test_approval_session_round_trip(self):
        now = datetime(2025, 1, 15, 14, 34, 0)
        session = ApprovalSession(
            session_id="session_001",
            run_id="run_001",
            items=[
                ApprovalItem(
                    "item_1", "headline", "old", "new", created_at=now
                )
            ],
            created_at=now,
            notification_sent=True,
        )
        restored = ApprovalSession.from_dict(session.to_dict())
        assert restored.session_id == session.session_id
        assert restored.notification_sent is True
        assert len(restored.items) == 1


class TestEngagementModels:
    def test_engagement_snapshot_round_trip(self):
        now = datetime(2025, 1, 15, 14, 0, 0)
        snap = EngagementSnapshot(
            timestamp=now,
            profile_views=100,
            connection_requests=5,
            post_engagement={"likes": 50, "comments": 10, "shares": 3, "impressions": 500},
        )
        assert EngagementSnapshot.from_dict(snap.to_dict()) == snap

    def test_engagement_comparison_round_trip(self):
        comp = EngagementComparison(
            metric_name="profile_views",
            baseline_value=100.0,
            current_value=150.0,
            absolute_change=50.0,
            percentage_change=50.0,
        )
        assert EngagementComparison.from_dict(comp.to_dict()) == comp

    def test_engagement_report_round_trip(self):
        now = datetime(2025, 1, 15, 14, 0, 0)
        report = EngagementReport(
            change_id="change_001",
            section_name="headline",
            applied_at=now,
            days_elapsed=7,
            comparisons=[
                EngagementComparison("views", 100.0, 150.0, 50.0, 50.0)
            ],
            overall_trend="improving",
        )
        assert EngagementReport.from_dict(report.to_dict()) == report


class TestRunMetadata:
    def test_round_trip_completed(self):
        start = datetime(2025, 1, 15, 14, 30, 0)
        end = datetime(2025, 1, 15, 14, 35, 0)
        meta = RunMetadata(
            run_id="run_001",
            start_time=start,
            end_time=end,
            status=PipelineStatus.COMPLETED,
            summary="All good",
            error=None,
        )
        assert RunMetadata.from_dict(meta.to_dict()) == meta

    def test_round_trip_failed(self):
        start = datetime(2025, 1, 15, 14, 30, 0)
        meta = RunMetadata(
            run_id="run_002",
            start_time=start,
            end_time=None,
            status=PipelineStatus.FAILED,
            summary=None,
            error="Connection timeout",
        )
        assert RunMetadata.from_dict(meta.to_dict()) == meta


class TestConfigModels:
    def test_hf_model_config_round_trip(self):
        cfg = HFModelConfig(
            model_id="mistralai/Mistral-7B-Instruct-v0.3",
            fallback_model_id="google/gemma-2-9b-it",
            api_token="hf_test_token",
            timeout_seconds=30,
            max_retries=3,
            backoff_base_seconds=2,
        )
        assert HFModelConfig.from_dict(cfg.to_dict()) == cfg

    def test_pipeline_config_round_trip(self):
        cfg = PipelineConfig(
            linkedin_profile_url="https://www.linkedin.com/in/testuser",
            github_username="testuser",
            schedule_interval=ScheduleInterval.WEEKLY,
            analyzer_model_id="mistralai/Mistral-7B-Instruct-v0.3",
            content_model_id="mistralai/Mistral-7B-Instruct-v0.3",
            fallback_model_id="google/gemma-2-9b-it",
            data_dir="./data",
            hf_api_token="hf_token",
            hf_timeout_seconds=30,
            hf_max_retries=3,
            approval_expiry_days=7,
        )
        restored = PipelineConfig.from_dict(cfg.to_dict())
        assert restored.linkedin_profile_url == cfg.linkedin_profile_url
        assert restored.schedule_interval == ScheduleInterval.WEEKLY
        assert restored.github_username == "testuser"

    def test_pipeline_config_no_schedule(self):
        cfg = PipelineConfig(
            linkedin_profile_url="https://www.linkedin.com/in/testuser",
            github_username=None,
            schedule_interval=None,
            analyzer_model_id="model",
            content_model_id="model",
            fallback_model_id="fallback",
            data_dir="./data",
            hf_api_token="token",
        )
        restored = PipelineConfig.from_dict(cfg.to_dict())
        assert restored.schedule_interval is None
        assert restored.github_username is None
