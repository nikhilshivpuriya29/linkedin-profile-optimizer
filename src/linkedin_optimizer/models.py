"""Core data models for the LinkedIn Profile Optimizer pipeline."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


# --- Enums ---


class PipelineStatus(Enum):
    """Status of the pipeline execution."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class ScheduleInterval(Enum):
    """Supported scheduling intervals."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Priority(Enum):
    """Priority level for recommendations."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApprovalStatus(Enum):
    """Status of an approval item."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"
    EXPIRED = "expired"


# --- Profile Scraper Models ---


@dataclass
class ProfileData:
    """Extracted LinkedIn profile data."""

    headline: str = ""
    about: str = ""
    experience: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    endorsements: list[dict] = field(default_factory=list)
    posts: list[dict] = field(default_factory=list)
    banner_url: Optional[str] = None
    photo_url: Optional[str] = None
    education: list[dict] = field(default_factory=list)
    certifications: list[dict] = field(default_factory=list)
    follower_count: int = 0
    connection_count: int = 0
    profile_views: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "headline": self.headline,
            "about": self.about,
            "experience": self.experience,
            "skills": self.skills,
            "endorsements": self.endorsements,
            "posts": self.posts,
            "banner_url": self.banner_url,
            "photo_url": self.photo_url,
            "education": self.education,
            "certifications": self.certifications,
            "follower_count": self.follower_count,
            "connection_count": self.connection_count,
            "profile_views": self.profile_views,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileData":
        return cls(
            headline=data.get("headline", ""),
            about=data.get("about", ""),
            experience=data.get("experience", []),
            skills=data.get("skills", []),
            endorsements=data.get("endorsements", []),
            posts=data.get("posts", []),
            banner_url=data.get("banner_url"),
            photo_url=data.get("photo_url"),
            education=data.get("education", []),
            certifications=data.get("certifications", []),
            follower_count=data.get("follower_count", 0),
            connection_count=data.get("connection_count", 0),
            profile_views=data.get("profile_views"),
        )


@dataclass
class ExtractionResult:
    """Result of LinkedIn profile extraction."""

    success: bool
    profile_data: Optional[ProfileData]
    failed_sections: list[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "profile_data": self.profile_data.to_dict() if self.profile_data else None,
            "failed_sections": self.failed_sections,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExtractionResult":
        profile_data = None
        if data.get("profile_data") is not None:
            profile_data = ProfileData.from_dict(data["profile_data"])
        return cls(
            success=data["success"],
            profile_data=profile_data,
            failed_sections=data.get("failed_sections", []),
            error_message=data.get("error_message"),
        )


# --- GitHub Extractor Models ---


@dataclass
class GitHubRepo:
    """A GitHub repository."""

    name: str
    description: Optional[str]
    stars: int
    primary_language: Optional[str]
    is_pinned: bool = False
    url: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "stars": self.stars,
            "primary_language": self.primary_language,
            "is_pinned": self.is_pinned,
            "url": self.url,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubRepo":
        return cls(
            name=data["name"],
            description=data.get("description"),
            stars=data.get("stars", 0),
            primary_language=data.get("primary_language"),
            is_pinned=data.get("is_pinned", False),
            url=data.get("url", ""),
        )


@dataclass
class GitHubContributions:
    """GitHub contribution activity over 12 months."""

    total_commits_12m: int = 0
    total_prs_12m: int = 0
    total_issues_12m: int = 0
    commits_per_week_avg: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_commits_12m": self.total_commits_12m,
            "total_prs_12m": self.total_prs_12m,
            "total_issues_12m": self.total_issues_12m,
            "commits_per_week_avg": self.commits_per_week_avg,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubContributions":
        return cls(
            total_commits_12m=data.get("total_commits_12m", 0),
            total_prs_12m=data.get("total_prs_12m", 0),
            total_issues_12m=data.get("total_issues_12m", 0),
            commits_per_week_avg=data.get("commits_per_week_avg", 0.0),
        )


@dataclass
class GitHubData:
    """Aggregated GitHub profile data."""

    repos: list[GitHubRepo] = field(default_factory=list)
    contributions: GitHubContributions = field(default_factory=GitHubContributions)
    pinned_repos: list[GitHubRepo] = field(default_factory=list)
    languages: dict[str, int] = field(default_factory=dict)
    notable_repos: list[GitHubRepo] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repos": [r.to_dict() for r in self.repos],
            "contributions": self.contributions.to_dict(),
            "pinned_repos": [r.to_dict() for r in self.pinned_repos],
            "languages": self.languages,
            "notable_repos": [r.to_dict() for r in self.notable_repos],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubData":
        return cls(
            repos=[GitHubRepo.from_dict(r) for r in data.get("repos", [])],
            contributions=GitHubContributions.from_dict(
                data.get("contributions", {})
            ),
            pinned_repos=[
                GitHubRepo.from_dict(r) for r in data.get("pinned_repos", [])
            ],
            languages=data.get("languages", {}),
            notable_repos=[
                GitHubRepo.from_dict(r) for r in data.get("notable_repos", [])
            ],
        )


@dataclass
class GitHubExtractionResult:
    """Result of GitHub data extraction."""

    success: bool
    data: Optional[GitHubData]
    partial: bool = False
    unavailable_categories: list[str] = field(default_factory=list)
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data.to_dict() if self.data else None,
            "partial": self.partial,
            "unavailable_categories": self.unavailable_categories,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubExtractionResult":
        github_data = None
        if data.get("data") is not None:
            github_data = GitHubData.from_dict(data["data"])
        return cls(
            success=data["success"],
            data=github_data,
            partial=data.get("partial", False),
            unavailable_categories=data.get("unavailable_categories", []),
            error_message=data.get("error_message"),
        )


# --- Analyzer Agent Models ---


@dataclass
class FactorScore:
    """Score for an individual scoring factor."""

    factor_name: str
    score: int  # 0-100
    explanation: str

    def to_dict(self) -> dict:
        return {
            "factor_name": self.factor_name,
            "score": self.score,
            "explanation": self.explanation,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FactorScore":
        return cls(
            factor_name=data["factor_name"],
            score=data["score"],
            explanation=data.get("explanation", ""),
        )


@dataclass
class SectionScore:
    """Score for a profile section with breakdown by factors."""

    section_name: str
    overall_score: int  # 0-100 weighted average
    factor_scores: list[FactorScore]
    missing: bool = False
    excluded_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "section_name": self.section_name,
            "overall_score": self.overall_score,
            "factor_scores": [f.to_dict() for f in self.factor_scores],
            "missing": self.missing,
            "excluded_factors": self.excluded_factors,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SectionScore":
        return cls(
            section_name=data["section_name"],
            overall_score=data["overall_score"],
            factor_scores=[
                FactorScore.from_dict(f) for f in data.get("factor_scores", [])
            ],
            missing=data.get("missing", False),
            excluded_factors=data.get("excluded_factors", []),
        )


@dataclass
class Recommendation:
    """A single actionable recommendation."""

    element: str
    modification: str
    priority: Priority
    guideline_reference: str
    expected_impact: str

    def to_dict(self) -> dict:
        return {
            "element": self.element,
            "modification": self.modification,
            "priority": self.priority.value,
            "guideline_reference": self.guideline_reference,
            "expected_impact": self.expected_impact,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Recommendation":
        return cls(
            element=data["element"],
            modification=data["modification"],
            priority=Priority(data["priority"]),
            guideline_reference=data.get("guideline_reference", ""),
            expected_impact=data.get("expected_impact", ""),
        )


@dataclass
class SectionInsight:
    """Insights for a profile section including strengths, weaknesses, recommendations."""

    section_name: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[Recommendation]

    def to_dict(self) -> dict:
        return {
            "section_name": self.section_name,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SectionInsight":
        return cls(
            section_name=data["section_name"],
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            recommendations=[
                Recommendation.from_dict(r) for r in data.get("recommendations", [])
            ],
        )


@dataclass
class OptimizationReport:
    """Full optimization report produced by the Analyzer Agent."""

    sections: list[SectionScore]
    insights: list[SectionInsight]
    overall_score: int
    github_summary: Optional[str] = None
    excluded_sections: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "sections": [s.to_dict() for s in self.sections],
            "insights": [i.to_dict() for i in self.insights],
            "overall_score": self.overall_score,
            "github_summary": self.github_summary,
            "excluded_sections": self.excluded_sections,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OptimizationReport":
        return cls(
            sections=[SectionScore.from_dict(s) for s in data.get("sections", [])],
            insights=[SectionInsight.from_dict(i) for i in data.get("insights", [])],
            overall_score=data.get("overall_score", 0),
            github_summary=data.get("github_summary"),
            excluded_sections=data.get("excluded_sections", []),
            generated_at=data.get("generated_at", ""),
        )


# --- Content Creator Agent Models ---


@dataclass
class HeadlineSuggestion:
    """Optimized headline suggestion."""

    text: str  # Max 220 chars
    keywords_used: list[str]
    value_proposition: str

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "keywords_used": self.keywords_used,
            "value_proposition": self.value_proposition,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HeadlineSuggestion":
        return cls(
            text=data["text"],
            keywords_used=data.get("keywords_used", []),
            value_proposition=data.get("value_proposition", ""),
        )


@dataclass
class AboutSuggestion:
    """Optimized about section suggestion."""

    text: str  # Max 2600 chars
    hook_sentence: str
    keywords_used: list[str]
    call_to_action: str

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "hook_sentence": self.hook_sentence,
            "keywords_used": self.keywords_used,
            "call_to_action": self.call_to_action,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AboutSuggestion":
        return cls(
            text=data["text"],
            hook_sentence=data.get("hook_sentence", ""),
            keywords_used=data.get("keywords_used", []),
            call_to_action=data.get("call_to_action", ""),
        )


@dataclass
class ExperienceSuggestion:
    """Optimized experience section suggestion."""

    role_title: str
    company: str
    bullets: list[str]  # Each max 2000 chars total per position
    metrics_included: bool
    qualitative_note: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "role_title": self.role_title,
            "company": self.company,
            "bullets": self.bullets,
            "metrics_included": self.metrics_included,
            "qualitative_note": self.qualitative_note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ExperienceSuggestion":
        return cls(
            role_title=data["role_title"],
            company=data["company"],
            bullets=data.get("bullets", []),
            metrics_included=data.get("metrics_included", False),
            qualitative_note=data.get("qualitative_note"),
        )


@dataclass
class PostIdea:
    """A content post idea suggestion."""

    topic: str
    format: str  # text, carousel, poll, video
    content_outline: str  # At least 2 sentences

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "format": self.format,
            "content_outline": self.content_outline,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PostIdea":
        return cls(
            topic=data["topic"],
            format=data["format"],
            content_outline=data.get("content_outline", ""),
        )


@dataclass
class BannerSuggestion:
    """Banner design suggestion."""

    dimensions: str  # e.g. "1584x396"
    color_palette: list[str]  # Up to 5 hex colors
    tagline: str  # Max 10 words

    def to_dict(self) -> dict:
        return {
            "dimensions": self.dimensions,
            "color_palette": self.color_palette,
            "tagline": self.tagline,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BannerSuggestion":
        return cls(
            dimensions=data["dimensions"],
            color_palette=data.get("color_palette", []),
            tagline=data.get("tagline", ""),
        )


@dataclass
class ContentPackage:
    """Complete content package generated by the Content Creator Agent."""

    headline: Optional[HeadlineSuggestion] = None
    about: Optional[AboutSuggestion] = None
    experience: list[ExperienceSuggestion] = field(default_factory=list)
    post_ideas: list[PostIdea] = field(default_factory=list)
    banner: Optional[BannerSuggestion] = None
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "headline": self.headline.to_dict() if self.headline else None,
            "about": self.about.to_dict() if self.about else None,
            "experience": [e.to_dict() for e in self.experience],
            "post_ideas": [p.to_dict() for p in self.post_ideas],
            "banner": self.banner.to_dict() if self.banner else None,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContentPackage":
        headline = None
        if data.get("headline") is not None:
            headline = HeadlineSuggestion.from_dict(data["headline"])
        about = None
        if data.get("about") is not None:
            about = AboutSuggestion.from_dict(data["about"])
        banner = None
        if data.get("banner") is not None:
            banner = BannerSuggestion.from_dict(data["banner"])
        return cls(
            headline=headline,
            about=about,
            experience=[
                ExperienceSuggestion.from_dict(e)
                for e in data.get("experience", [])
            ],
            post_ideas=[PostIdea.from_dict(p) for p in data.get("post_ideas", [])],
            banner=banner,
            generated_at=data.get("generated_at", ""),
        )


# --- Approval Workflow Models ---


@dataclass
class ApprovalItem:
    """A single item awaiting approval."""

    item_id: str
    section_name: str
    current_content: str
    proposed_content: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    user_feedback: Optional[str] = None  # Max 500 chars
    rejection_reason: Optional[str] = None  # Max 500 chars
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None  # 7 days from creation
    decided_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "section_name": self.section_name,
            "current_content": self.current_content,
            "proposed_content": self.proposed_content,
            "status": self.status.value,
            "user_feedback": self.user_feedback,
            "rejection_reason": self.rejection_reason,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalItem":
        created_at = datetime.fromisoformat(data["created_at"])
        expires_at = None
        if data.get("expires_at") is not None:
            expires_at = datetime.fromisoformat(data["expires_at"])
        decided_at = None
        if data.get("decided_at") is not None:
            decided_at = datetime.fromisoformat(data["decided_at"])
        return cls(
            item_id=data["item_id"],
            section_name=data["section_name"],
            current_content=data["current_content"],
            proposed_content=data["proposed_content"],
            status=ApprovalStatus(data.get("status", "pending")),
            user_feedback=data.get("user_feedback"),
            rejection_reason=data.get("rejection_reason"),
            created_at=created_at,
            expires_at=expires_at,
            decided_at=decided_at,
        )


@dataclass
class ApprovalSession:
    """A session containing multiple approval items."""

    session_id: str
    run_id: str
    items: list[ApprovalItem]
    created_at: datetime
    notification_sent: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at.isoformat(),
            "notification_sent": self.notification_sent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalSession":
        return cls(
            session_id=data["session_id"],
            run_id=data["run_id"],
            items=[ApprovalItem.from_dict(i) for i in data.get("items", [])],
            created_at=datetime.fromisoformat(data["created_at"]),
            notification_sent=data.get("notification_sent", False),
        )


# --- Engagement Tracking Models ---


@dataclass
class EngagementSnapshot:
    """A point-in-time snapshot of engagement metrics."""

    timestamp: datetime
    profile_views: int
    connection_requests: int
    post_engagement: dict  # {likes, comments, shares, impressions}

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "profile_views": self.profile_views,
            "connection_requests": self.connection_requests,
            "post_engagement": self.post_engagement,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EngagementSnapshot":
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            profile_views=data.get("profile_views", 0),
            connection_requests=data.get("connection_requests", 0),
            post_engagement=data.get("post_engagement", {}),
        )


@dataclass
class EngagementComparison:
    """Comparison of a single metric between baseline and current."""

    metric_name: str
    baseline_value: float
    current_value: float
    absolute_change: float
    percentage_change: float

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "baseline_value": self.baseline_value,
            "current_value": self.current_value,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EngagementComparison":
        return cls(
            metric_name=data["metric_name"],
            baseline_value=data.get("baseline_value", 0.0),
            current_value=data.get("current_value", 0.0),
            absolute_change=data.get("absolute_change", 0.0),
            percentage_change=data.get("percentage_change", 0.0),
        )


@dataclass
class EngagementReport:
    """Report comparing engagement before and after a change."""

    change_id: str
    section_name: str
    applied_at: datetime
    days_elapsed: int
    comparisons: list[EngagementComparison]
    overall_trend: str  # "improving", "declining", "stable"

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "section_name": self.section_name,
            "applied_at": self.applied_at.isoformat(),
            "days_elapsed": self.days_elapsed,
            "comparisons": [c.to_dict() for c in self.comparisons],
            "overall_trend": self.overall_trend,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EngagementReport":
        return cls(
            change_id=data["change_id"],
            section_name=data["section_name"],
            applied_at=datetime.fromisoformat(data["applied_at"]),
            days_elapsed=data.get("days_elapsed", 0),
            comparisons=[
                EngagementComparison.from_dict(c)
                for c in data.get("comparisons", [])
            ],
            overall_trend=data.get("overall_trend", "stable"),
        )


# --- Pipeline Orchestrator Models ---


@dataclass
class RunMetadata:
    """Metadata for a single pipeline run."""

    run_id: str
    start_time: datetime
    end_time: Optional[datetime]
    status: PipelineStatus
    summary: Optional[str]
    error: Optional[str]

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "summary": self.summary,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunMetadata":
        end_time = None
        if data.get("end_time") is not None:
            end_time = datetime.fromisoformat(data["end_time"])
        return cls(
            run_id=data["run_id"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=end_time,
            status=PipelineStatus(data["status"]),
            summary=data.get("summary"),
            error=data.get("error"),
        )
