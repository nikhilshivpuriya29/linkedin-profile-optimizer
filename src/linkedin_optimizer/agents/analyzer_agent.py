"""Analyzer Agent for scoring LinkedIn profile sections and generating insights."""

import json
import logging
from datetime import datetime
from typing import Optional

from linkedin_optimizer.integrations.hf_client import HuggingFaceClient
from linkedin_optimizer.models import (
    FactorScore,
    GitHubData,
    OptimizationReport,
    Priority,
    ProfileData,
    Recommendation,
    SectionInsight,
    SectionScore,
)

logger = logging.getLogger(__name__)

# Priority ordering for sorting recommendations
_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}

# Section-specific scoring factors per requirements 2.2-2.7
SECTION_FACTORS: dict[str, list[dict[str, str]]] = {
    "headline": [
        {
            "name": "keyword_presence",
            "description": "Presence of role-relevant keywords that improve LinkedIn search visibility",
        },
        {
            "name": "character_utilization",
            "description": "Character length relative to the platform maximum of 220 characters",
        },
        {
            "name": "value_proposition",
            "description": "Whether the headline contains a measurable value proposition or unique differentiator",
        },
    ],
    "about": [
        {
            "name": "narrative_structure",
            "description": "Presence of a narrative structure with beginning, middle, and end",
        },
        {
            "name": "keyword_density",
            "description": "Keyword density between 1% and 3% of total word count",
        },
        {
            "name": "call_to_action",
            "description": "Presence of at least one call-to-action",
        },
        {
            "name": "character_utilization",
            "description": "Whether the section uses at least 40% of the 2600-character limit",
        },
    ],
    "experience": [
        {
            "name": "numeric_metrics",
            "description": "Percentage of bullet points containing numeric metrics",
        },
        {
            "name": "action_verbs",
            "description": "Use of action verbs at the start of each bullet",
        },
        {
            "name": "role_alignment",
            "description": "Alignment of job titles and descriptions with the user's stated target role",
        },
        {
            "name": "formatting_consistency",
            "description": "Consistent use of bullet-point formatting across entries",
        },
    ],
    "skills": [
        {
            "name": "role_alignment",
            "description": "Alignment of listed skills with the user's stated target role",
        },
        {
            "name": "endorsement_count",
            "description": "Number of endorsements per skill",
        },
        {
            "name": "top_skills_match",
            "description": "Whether the top 3 pinned skills match the target role",
        },
    ],
    "posts": [
        {
            "name": "engagement_rate",
            "description": "Average engagement rate (reactions + comments / follower count) over recent 90 days",
        },
        {
            "name": "posting_frequency",
            "description": "Number of posts published in the most recent 90 days",
        },
        {
            "name": "topic_consistency",
            "description": "Consistency of topic alignment with the user's stated target role",
        },
    ],
    "banner_photo": [
        {
            "name": "custom_banner",
            "description": "Presence of a custom banner image (mandatory for professional standard)",
        },
        {
            "name": "photo_quality",
            "description": "Whether the photo meets minimum resolution of 400x400 pixels",
        },
        {
            "name": "brand_alignment",
            "description": "Visual alignment with the stated professional brand keywords in the profile",
        },
    ],
}

# LinkedIn optimization guidelines referenced in recommendations
LINKEDIN_GUIDELINES = {
    "headline": [
        "LinkedIn's algorithm prioritizes keyword-rich headlines for search ranking and profile discoverability",
        "Profiles with value propositions in headlines receive 30% more profile views according to LinkedIn data",
        "Using the full 220-character limit increases search visibility by including more relevant keywords",
    ],
    "about": [
        "LinkedIn recommends a narrative structure to keep readers engaged through the full About section",
        "Keyword density between 1-3% optimizes for LinkedIn's search algorithm without appearing spammy",
        "Profiles with a call-to-action in the About section generate 25% more connection requests",
        "Using at least 40% of the 2600-character limit signals depth and expertise to LinkedIn's algorithm",
    ],
    "experience": [
        "Bullet points with quantifiable metrics receive higher engagement from recruiters per LinkedIn Talent data",
        "Action verbs at the start of bullets improve readability and LinkedIn search indexing",
        "Consistent formatting across experience entries signals professionalism and attention to detail",
        "Role-aligned descriptions improve matching with LinkedIn's job recommendation algorithm",
    ],
    "skills": [
        "LinkedIn's algorithm uses endorsed skills to match profiles with relevant opportunities",
        "Top 3 pinned skills are the most visible and should align with your target role for maximum impact",
        "Skills with more endorsements rank higher in LinkedIn's skills assessment visibility",
    ],
    "posts": [
        "LinkedIn's algorithm rewards consistent posting with increased reach and profile visibility",
        "Posts with higher engagement rates signal thought leadership and boost profile authority",
        "Topic consistency builds topical authority which LinkedIn rewards with increased distribution",
    ],
    "banner_photo": [
        "Custom banners increase perceived professionalism and brand consistency per LinkedIn best practices",
        "Profile photos meeting minimum resolution appear more prominently in search results",
        "Visual branding alignment reinforces professional identity across the LinkedIn platform",
    ],
}


class AnalyzerAgent:
    """Scores profile sections and generates actionable insights.

    Uses the Hugging Face client for AI-powered analysis with a fallback
    heuristic scoring method for testability and resilience.

    Implements Requirements 2.1-2.9, 3.1-3.5.
    """

    def __init__(
        self,
        model_id: str,
        fallback_model_id: str,
        hf_client: Optional[HuggingFaceClient] = None,
    ) -> None:
        """Initialize the AnalyzerAgent.

        Args:
            model_id: Primary Hugging Face model ID for analysis.
            fallback_model_id: Fallback model ID if primary is unavailable.
            hf_client: HuggingFaceClient instance for AI generation.
                       If None, heuristic scoring will be used.
        """
        self.model_id = model_id
        self.fallback_model_id = fallback_model_id
        self.hf_client = hf_client

    async def analyze(
        self, profile: ProfileData, github: Optional[GitHubData] = None
    ) -> OptimizationReport:
        """Run the full analysis pipeline on a profile.

        Scores all sections, generates insights, and produces an OptimizationReport.

        Args:
            profile: Extracted LinkedIn profile data.
            github: Optional GitHub data for enrichment.

        Returns:
            A complete OptimizationReport with scores and insights.
        """
        # Score each section
        section_scores: list[SectionScore] = []

        # Map sections to their content
        section_content_map = self._extract_section_content(profile)

        for section_name, content in section_content_map.items():
            score = await self.score_section(section_name, content)
            section_scores.append(score)

        # Generate insights based on scores
        insights = await self.generate_insights(section_scores, profile)

        # Calculate overall score as average of non-missing section scores
        non_missing_scores = [s.overall_score for s in section_scores if not s.missing]
        overall_score = (
            round(sum(non_missing_scores) / len(non_missing_scores))
            if non_missing_scores
            else 0
        )

        # Build GitHub summary if data is available
        github_summary = self._build_github_summary(github) if github else None

        # Identify excluded sections (those that are missing)
        excluded_sections = [s.section_name for s in section_scores if s.missing]

        return OptimizationReport(
            sections=section_scores,
            insights=insights,
            overall_score=overall_score,
            github_summary=github_summary,
            excluded_sections=excluded_sections,
            generated_at=datetime.now().isoformat(),
        )

    async def score_section(self, section_name: str, content: str) -> SectionScore:
        """Score an individual profile section.

        Attempts AI-powered scoring via HF client first. Falls back to
        heuristic scoring if the client is unavailable or fails.

        Args:
            section_name: Name of the section (e.g., "headline", "about").
            content: The text content of the section.

        Returns:
            A SectionScore with factor breakdowns.
        """
        # Handle empty/missing sections (Req 2.8)
        if not content or not content.strip():
            factors = SECTION_FACTORS.get(section_name, [])
            factor_scores = [
                FactorScore(
                    factor_name=f["name"],
                    score=0,
                    explanation=f"Section '{section_name}' is missing or empty.",
                )
                for f in factors
            ]
            return SectionScore(
                section_name=section_name,
                overall_score=0,
                factor_scores=factor_scores,
                missing=True,
                excluded_factors=[],
            )

        # Try AI-powered scoring if client is available
        if self.hf_client is not None:
            try:
                return await self._ai_score_section(section_name, content)
            except Exception as e:
                logger.warning(
                    "AI scoring failed for section '%s': %s. Falling back to heuristic.",
                    section_name,
                    e,
                )

        # Fallback to heuristic scoring
        return self._heuristic_score_section(section_name, content)

    async def _ai_score_section(self, section_name: str, content: str) -> SectionScore:
        """Score a section using the HF model.

        Args:
            section_name: Name of the section.
            content: Content to score.

        Returns:
            SectionScore based on AI analysis.
        """
        prompt = self._build_scoring_prompt(section_name, content)
        system_context = (
            "You are a LinkedIn profile optimization expert. "
            "Analyze the given profile section and provide scoring as JSON. "
            "Be specific and actionable in your explanations."
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context=system_context,
            max_tokens=1024,
            temperature=0.3,
        )

        # Try to parse JSON response
        return self._parse_scoring_response(section_name, response.text, content)

    def _parse_scoring_response(
        self, section_name: str, response_text: str, content: str
    ) -> SectionScore:
        """Parse the AI model's scoring response.

        Falls back to heuristic if JSON parsing fails.
        """
        try:
            # Try to extract JSON from the response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                data = json.loads(json_str)

                factor_scores: list[FactorScore] = []
                excluded_factors: list[str] = []

                if "factors" in data:
                    for factor_data in data["factors"]:
                        score = int(factor_data.get("score", -1))
                        if score < 0:
                            # Factor unavailable (Req 2.9)
                            excluded_factors.append(factor_data.get("name", "unknown"))
                        else:
                            factor_scores.append(
                                FactorScore(
                                    factor_name=factor_data.get("name", "unknown"),
                                    score=max(0, min(100, score)),
                                    explanation=factor_data.get("explanation", ""),
                                )
                            )

                overall = self._calculate_weighted_average(factor_scores)

                return SectionScore(
                    section_name=section_name,
                    overall_score=overall,
                    factor_scores=factor_scores,
                    missing=False,
                    excluded_factors=excluded_factors,
                )
        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            logger.warning(
                "Failed to parse AI response for section '%s': %s. Using heuristic.",
                section_name,
                e,
            )

        # Fallback to heuristic if parsing fails
        return self._heuristic_score_section(section_name, content)

    def _heuristic_score_section(self, section_name: str, content: str) -> SectionScore:
        """Rule-based scoring without calling the AI model.

        Provides deterministic scoring based on content characteristics
        for testability and as a fallback when the model is unavailable.

        Args:
            section_name: Name of the section to score.
            content: The text content of the section.

        Returns:
            SectionScore with heuristic factor scores.
        """
        factors = SECTION_FACTORS.get(section_name, [])
        factor_scores: list[FactorScore] = []
        excluded_factors: list[str] = []

        for factor in factors:
            score, explanation, available = self._score_factor_heuristic(
                section_name, factor["name"], content
            )
            if not available:
                excluded_factors.append(factor["name"])
            else:
                factor_scores.append(
                    FactorScore(
                        factor_name=factor["name"],
                        score=max(0, min(100, score)),
                        explanation=explanation,
                    )
                )

        overall = self._calculate_weighted_average(factor_scores)

        return SectionScore(
            section_name=section_name,
            overall_score=overall,
            factor_scores=factor_scores,
            missing=False,
            excluded_factors=excluded_factors,
        )

    def _score_factor_heuristic(
        self, section_name: str, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score an individual factor using heuristics.

        Returns:
            Tuple of (score, explanation, is_available).
            If is_available is False, the factor should be excluded.
        """
        if section_name == "headline":
            return self._score_headline_factor(factor_name, content)
        elif section_name == "about":
            return self._score_about_factor(factor_name, content)
        elif section_name == "experience":
            return self._score_experience_factor(factor_name, content)
        elif section_name == "skills":
            return self._score_skills_factor(factor_name, content)
        elif section_name == "posts":
            return self._score_posts_factor(factor_name, content)
        elif section_name == "banner_photo":
            return self._score_banner_photo_factor(factor_name, content)
        else:
            # Unknown section — basic length heuristic
            length = len(content)
            score = min(100, length // 2)
            return score, f"Section has {length} characters.", True

    def _score_headline_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score headline-specific factors."""
        if factor_name == "keyword_presence":
            # Check for common professional keywords
            keywords = [
                "engineer",
                "developer",
                "manager",
                "lead",
                "senior",
                "specialist",
                "consultant",
                "architect",
                "designer",
                "analyst",
                "director",
                "founder",
                "ceo",
                "cto",
            ]
            found = [k for k in keywords if k.lower() in content.lower()]
            if len(found) >= 2:
                score = 80
                explanation = f"Contains relevant keywords: {', '.join(found)}"
            elif len(found) == 1:
                score = 55
                explanation = f"Contains keyword '{found[0]}' but could include more"
            else:
                score = 25
                explanation = "No role-relevant keywords detected"
            return score, explanation, True

        elif factor_name == "character_utilization":
            length = len(content)
            max_chars = 220
            utilization = length / max_chars
            if utilization >= 0.7:
                score = 85
                explanation = f"Good utilization: {length}/{max_chars} characters ({utilization:.0%})"
            elif utilization >= 0.4:
                score = 60
                explanation = f"Moderate utilization: {length}/{max_chars} characters ({utilization:.0%})"
            else:
                score = 30
                explanation = f"Low utilization: {length}/{max_chars} characters ({utilization:.0%})"
            return score, explanation, True

        elif factor_name == "value_proposition":
            # Check for value-indicating patterns
            value_indicators = ["|", "helping", "driving", "enabling", "building", "creating", "%", "x "]
            has_value = any(ind.lower() in content.lower() for ind in value_indicators)
            if has_value:
                score = 75
                explanation = "Contains a value proposition or differentiator"
            else:
                score = 30
                explanation = "No clear value proposition or differentiator detected"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _score_about_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score about section factors."""
        if factor_name == "narrative_structure":
            # Check for paragraph structure (multiple paragraphs suggest narrative)
            paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
            sentences = content.count(".") + content.count("!") + content.count("?")
            if len(paragraphs) >= 3 and sentences >= 5:
                score = 80
                explanation = "Good narrative structure with multiple paragraphs"
            elif len(paragraphs) >= 2 or sentences >= 3:
                score = 55
                explanation = "Basic structure present but could be more developed"
            else:
                score = 25
                explanation = "Lacks clear narrative structure"
            return score, explanation, True

        elif factor_name == "keyword_density":
            words = content.split()
            word_count = len(words)
            if word_count == 0:
                return 0, "No words found.", True
            # Simple heuristic: check if there are repeated professional terms
            word_freq: dict[str, int] = {}
            for word in words:
                w = word.lower().strip(".,!?;:")
                if len(w) > 3:
                    word_freq[w] = word_freq.get(w, 0) + 1
            repeated = [w for w, c in word_freq.items() if c >= 2]
            density_estimate = len(repeated) / max(1, word_count) * 100
            if 1 <= density_estimate <= 3:
                score = 80
                explanation = f"Good keyword density (~{density_estimate:.1f}%)"
            elif density_estimate > 3:
                score = 50
                explanation = f"Keyword density may be too high (~{density_estimate:.1f}%)"
            else:
                score = 40
                explanation = f"Low keyword repetition (~{density_estimate:.1f}%)"
            return score, explanation, True

        elif factor_name == "call_to_action":
            cta_indicators = [
                "connect",
                "reach out",
                "contact",
                "let's",
                "message me",
                "email",
                "schedule",
                "book",
                "visit",
                "check out",
            ]
            has_cta = any(ind.lower() in content.lower() for ind in cta_indicators)
            if has_cta:
                score = 80
                explanation = "Contains a call-to-action"
            else:
                score = 25
                explanation = "No call-to-action detected"
            return score, explanation, True

        elif factor_name == "character_utilization":
            length = len(content)
            max_chars = 2600
            utilization = length / max_chars
            if utilization >= 0.4:
                score = 80
                explanation = f"Good utilization: {length}/{max_chars} characters ({utilization:.0%})"
            elif utilization >= 0.2:
                score = 55
                explanation = f"Moderate utilization: {length}/{max_chars} characters ({utilization:.0%})"
            else:
                score = 25
                explanation = f"Low utilization: {length}/{max_chars} characters ({utilization:.0%})"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _score_experience_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score experience section factors."""
        if factor_name == "numeric_metrics":
            # Count lines with numbers/percentages
            lines = [l.strip() for l in content.split("\n") if l.strip()]
            if not lines:
                return 20, "No content lines found.", True
            lines_with_numbers = sum(
                1 for line in lines if any(c.isdigit() for c in line)
            )
            ratio = lines_with_numbers / len(lines)
            if ratio >= 0.5:
                score = 85
                explanation = f"{lines_with_numbers}/{len(lines)} bullets contain metrics"
            elif ratio >= 0.25:
                score = 55
                explanation = f"Only {lines_with_numbers}/{len(lines)} bullets contain metrics"
            else:
                score = 25
                explanation = "Very few bullets contain numeric metrics"
            return score, explanation, True

        elif factor_name == "action_verbs":
            action_verbs = [
                "led",
                "developed",
                "built",
                "designed",
                "implemented",
                "managed",
                "created",
                "delivered",
                "improved",
                "reduced",
                "increased",
                "launched",
                "orchestrated",
                "optimized",
                "drove",
                "spearheaded",
                "architected",
                "streamlined",
            ]
            lines = [l.strip() for l in content.split("\n") if l.strip()]
            if not lines:
                return 20, "No content lines found.", True
            starts_with_action = sum(
                1
                for line in lines
                if any(
                    line.lower().lstrip("•-* ").startswith(v) for v in action_verbs
                )
            )
            ratio = starts_with_action / len(lines)
            if ratio >= 0.5:
                score = 80
                explanation = f"{starts_with_action}/{len(lines)} bullets start with action verbs"
            elif ratio >= 0.2:
                score = 50
                explanation = "Some bullets use action verbs but inconsistently"
            else:
                score = 25
                explanation = "Few bullets start with action verbs"
            return score, explanation, True

        elif factor_name == "role_alignment":
            # Basic check: content length and professional terminology
            if len(content) > 200:
                score = 65
                explanation = "Descriptions appear substantive and role-relevant"
            else:
                score = 40
                explanation = "Descriptions are brief; more role-specific detail would help"
            return score, explanation, True

        elif factor_name == "formatting_consistency":
            lines = [l.strip() for l in content.split("\n") if l.strip()]
            if not lines:
                return 20, "No content lines found.", True
            # Check for consistent bullet formatting
            bullet_chars = ["•", "-", "*"]
            bulleted = sum(
                1 for line in lines if any(line.startswith(c) for c in bullet_chars)
            )
            if bulleted >= len(lines) * 0.7:
                score = 80
                explanation = "Consistent bullet-point formatting"
            elif bulleted > 0:
                score = 50
                explanation = "Inconsistent formatting across entries"
            else:
                score = 35
                explanation = "No bullet-point formatting detected"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _score_skills_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score skills section factors."""
        if factor_name == "role_alignment":
            # Check number of skills listed
            skills_count = content.count(",") + 1 if content else 0
            if skills_count >= 10:
                score = 75
                explanation = f"Has {skills_count} skills listed"
            elif skills_count >= 5:
                score = 55
                explanation = f"Has {skills_count} skills, consider adding more"
            else:
                score = 30
                explanation = f"Only {skills_count} skills listed"
            return score, explanation, True

        elif factor_name == "endorsement_count":
            # Check for endorsement numbers in content
            has_numbers = any(c.isdigit() for c in content)
            if has_numbers:
                score = 60
                explanation = "Skills have endorsements"
            else:
                score = 35
                explanation = "No endorsement data available"
            # If no endorsement data at all, mark as unavailable
            if "endorsement" not in content.lower() and not has_numbers:
                return 0, "Endorsement data unavailable", False
            return score, explanation, True

        elif factor_name == "top_skills_match":
            # Without knowing target role, provide middle score
            if len(content) > 50:
                score = 60
                explanation = "Skills section has content for evaluation"
            else:
                score = 40
                explanation = "Skills section needs more detail for proper evaluation"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _score_posts_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score posts section factors."""
        if factor_name == "engagement_rate":
            # Check if post data indicates engagement metrics
            if not content or content.strip() == "[]":
                return 0, "No post data available for engagement analysis", False
            has_numbers = any(c.isdigit() for c in content)
            if has_numbers:
                score = 55
                explanation = "Posts show some engagement activity"
            else:
                score = 30
                explanation = "Cannot determine engagement rate from available data"
            return score, explanation, True

        elif factor_name == "posting_frequency":
            if not content or content.strip() == "[]":
                return 0, "No post data available for frequency analysis", False
            # Count mentions of posts (rough indicator)
            post_count = content.count("text") if "text" in content else 0
            if post_count >= 4:
                score = 75
                explanation = f"Active poster with ~{post_count} posts in data"
            elif post_count >= 2:
                score = 50
                explanation = f"Moderate posting frequency (~{post_count} posts)"
            else:
                score = 30
                explanation = "Low posting frequency"
            return score, explanation, True

        elif factor_name == "topic_consistency":
            if not content or content.strip() == "[]":
                return 0, "No post data available for topic analysis", False
            score = 50
            explanation = "Topic consistency requires deeper analysis"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _score_banner_photo_factor(
        self, factor_name: str, content: str
    ) -> tuple[int, str, bool]:
        """Score banner and photo factors."""
        if factor_name == "custom_banner":
            if content and "banner" in content.lower() and "http" in content.lower():
                score = 80
                explanation = "Custom banner image is present"
            elif content and "http" in content.lower():
                score = 60
                explanation = "Banner URL detected but may not be custom"
            else:
                score = 10
                explanation = "No custom banner image detected"
            return score, explanation, True

        elif factor_name == "photo_quality":
            if content and "http" in content.lower():
                score = 65
                explanation = "Profile photo is present (resolution cannot be verified from URL alone)"
            else:
                score = 10
                explanation = "No profile photo detected"
            return score, explanation, True

        elif factor_name == "brand_alignment":
            if content and len(content) > 20:
                score = 50
                explanation = "Visual assets present; brand alignment requires visual analysis"
            else:
                score = 20
                explanation = "Insufficient visual assets for brand evaluation"
            return score, explanation, True

        return 50, "Factor could not be evaluated.", True

    def _build_scoring_prompt(self, section_name: str, content: str) -> str:
        """Construct a section-specific scoring prompt for the AI model.

        Builds prompts that ask the model to evaluate based on the specific
        factors defined for each section per Requirements 2.2-2.7.

        Args:
            section_name: The section being scored.
            content: The content to evaluate.

        Returns:
            A formatted prompt string.
        """
        factors = SECTION_FACTORS.get(section_name, [])
        factors_description = "\n".join(
            f"  - {f['name']}: {f['description']}" for f in factors
        )

        prompt = f"""Analyze the following LinkedIn '{section_name}' section content and score it on each factor from 0-100.

Content to analyze:
---
{content}
---

Score the following factors (0-100 each):
{factors_description}

For each factor, provide:
- A numeric score (0-100). Use -1 if the factor cannot be evaluated due to missing data.
- A brief explanation of the score.

Respond ONLY in this exact JSON format:
{{
  "factors": [
    {{"name": "<factor_name>", "score": <0-100 or -1>, "explanation": "<brief explanation>"}}
  ]
}}
"""
        return prompt

    def _calculate_weighted_average(self, factors: list[FactorScore]) -> int:
        """Calculate weighted average of factor scores.

        Excludes any factors with score < 0 (unavailable).
        Clamps the result to 0-100.

        Args:
            factors: List of FactorScore objects.

        Returns:
            Weighted average score as an integer, clamped to 0-100.
        """
        # Filter out unavailable factors (score < 0)
        available = [f for f in factors if f.score >= 0]
        if not available:
            return 0

        # Equal weighting across all available factors
        total = sum(f.score for f in available)
        average = total / len(available)

        # Clamp to 0-100
        return max(0, min(100, round(average)))

    async def generate_insights(
        self, scores: list[SectionScore], profile: ProfileData
    ) -> list[SectionInsight]:
        """Generate actionable insights for all scored sections.

        For each section, produces at least 1 strength, 1 weakness, and
        1 recommendation. If the section scores below 70, produces at least
        2 recommendations.

        Each recommendation has a priority (High/Medium/Low) and references
        at least 1 LinkedIn optimization guideline.

        Args:
            scores: List of SectionScore objects from scoring.
            profile: The profile data for context.

        Returns:
            List of SectionInsight objects, one per scored section.
        """
        insights: list[SectionInsight] = []

        for section_score in scores:
            insight = self._generate_section_insight(section_score, profile)
            insights.append(insight)

        return insights

    def _generate_section_insight(
        self, section_score: SectionScore, profile: ProfileData
    ) -> SectionInsight:
        """Generate insight for a single section.

        Args:
            section_score: The score for the section.
            profile: The profile data for context.

        Returns:
            SectionInsight with strengths, weaknesses, and recommendations.
        """
        section_name = section_score.section_name
        score = section_score.overall_score
        factor_scores = section_score.factor_scores

        # Generate strengths (at least 1)
        strengths = self._identify_strengths(section_name, factor_scores, score)
        if not strengths:
            strengths = [f"The {section_name} section exists on the profile"]

        # Generate weaknesses (at least 1)
        weaknesses = self._identify_weaknesses(section_name, factor_scores, score)
        if not weaknesses:
            weaknesses = [f"The {section_name} section could be further optimized"]

        # Generate recommendations (at least 1, at least 2 if score < 70)
        min_recommendations = 2 if score < 70 else 1
        recommendations = self._generate_recommendations(
            section_name, factor_scores, score, min_recommendations
        )

        # Order recommendations by priority (HIGH > MEDIUM > LOW)
        recommendations.sort(key=lambda r: _PRIORITY_ORDER[r.priority])

        return SectionInsight(
            section_name=section_name,
            strengths=strengths,
            weaknesses=weaknesses,
            recommendations=recommendations,
        )

    def _identify_strengths(
        self, section_name: str, factors: list[FactorScore], overall_score: int
    ) -> list[str]:
        """Identify strengths from factor scores."""
        strengths: list[str] = []

        for factor in factors:
            if factor.score >= 70:
                strengths.append(
                    f"Strong {factor.factor_name.replace('_', ' ')}: {factor.explanation}"
                )

        if overall_score >= 70 and not strengths:
            strengths.append(
                f"The {section_name} section scores well overall ({overall_score}/100)"
            )

        return strengths

    def _identify_weaknesses(
        self, section_name: str, factors: list[FactorScore], overall_score: int
    ) -> list[str]:
        """Identify weaknesses from factor scores."""
        weaknesses: list[str] = []

        for factor in factors:
            if factor.score < 50:
                weaknesses.append(
                    f"Weak {factor.factor_name.replace('_', ' ')}: {factor.explanation}"
                )

        if overall_score < 50 and not weaknesses:
            weaknesses.append(
                f"The {section_name} section needs significant improvement ({overall_score}/100)"
            )

        return weaknesses

    def _generate_recommendations(
        self,
        section_name: str,
        factors: list[FactorScore],
        overall_score: int,
        min_count: int,
    ) -> list[Recommendation]:
        """Generate prioritized recommendations for a section.

        Each recommendation references at least 1 LinkedIn optimization guideline.

        Args:
            section_name: The section name.
            factors: The factor scores.
            overall_score: The overall section score.
            min_count: Minimum number of recommendations to produce.

        Returns:
            List of recommendations sorted by priority.
        """
        recommendations: list[Recommendation] = []
        guidelines = LINKEDIN_GUIDELINES.get(section_name, LINKEDIN_GUIDELINES.get("headline", []))

        # Sort factors by score (lowest first) to prioritize weakest areas
        sorted_factors = sorted(factors, key=lambda f: f.score)

        guideline_idx = 0

        for factor in sorted_factors:
            if len(recommendations) >= max(min_count, 3):
                break

            # Determine priority based on factor score
            if factor.score < 40:
                priority = Priority.HIGH
            elif factor.score < 60:
                priority = Priority.MEDIUM
            else:
                priority = Priority.LOW

            # Only generate recommendations for factors that need improvement
            if factor.score >= 80:
                continue

            # Get a guideline reference
            guideline_ref = guidelines[guideline_idx % len(guidelines)] if guidelines else (
                "LinkedIn algorithm favors complete and optimized profiles"
            )
            guideline_idx += 1

            element, modification, impact = self._get_recommendation_details(
                section_name, factor.factor_name, factor.score
            )

            recommendations.append(
                Recommendation(
                    element=element,
                    modification=modification,
                    priority=priority,
                    guideline_reference=guideline_ref,
                    expected_impact=impact,
                )
            )

        # Ensure minimum recommendations are met
        while len(recommendations) < min_count:
            guideline_ref = guidelines[guideline_idx % len(guidelines)] if guidelines else (
                "LinkedIn algorithm favors complete and optimized profiles"
            )
            guideline_idx += 1

            recommendations.append(
                Recommendation(
                    element=f"{section_name} content",
                    modification=f"Optimize the {section_name} section for better engagement and visibility",
                    priority=Priority.MEDIUM if overall_score >= 50 else Priority.HIGH,
                    guideline_reference=guideline_ref,
                    expected_impact="Improved profile visibility and engagement metrics",
                )
            )

        return recommendations

    def _get_recommendation_details(
        self, section_name: str, factor_name: str, score: int
    ) -> tuple[str, str, str]:
        """Get specific recommendation details based on section and factor.

        Returns:
            Tuple of (element, modification, expected_impact).
        """
        details_map: dict[str, dict[str, tuple[str, str, str]]] = {
            "headline": {
                "keyword_presence": (
                    "headline keywords",
                    "Add role-relevant keywords that match your target position to improve search discoverability",
                    "15-25% increase in profile appearances in relevant searches",
                ),
                "character_utilization": (
                    "headline length",
                    "Expand headline to use more of the 220-character limit with relevant information",
                    "More keywords indexed by LinkedIn's search algorithm",
                ),
                "value_proposition": (
                    "headline value proposition",
                    "Add a measurable value proposition or unique differentiator (e.g., '| Driving 40% faster deployments')",
                    "Higher click-through rate from search results to profile",
                ),
            },
            "about": {
                "narrative_structure": (
                    "about section structure",
                    "Restructure with a clear beginning (hook), middle (achievements), and end (CTA)",
                    "Increased time spent reading your profile and higher connection request rate",
                ),
                "keyword_density": (
                    "about section keywords",
                    "Ensure keyword density is between 1-3% by naturally incorporating relevant terms",
                    "Better matching with LinkedIn's search and recommendation algorithms",
                ),
                "call_to_action": (
                    "about section CTA",
                    "Add a clear call-to-action directing readers to connect, message, or visit a link",
                    "25% increase in inbound connection requests",
                ),
                "character_utilization": (
                    "about section length",
                    "Expand content to use at least 40% of the 2600-character limit",
                    "Signals depth and expertise to LinkedIn's algorithm",
                ),
            },
            "experience": {
                "numeric_metrics": (
                    "experience metrics",
                    "Add quantifiable metrics (percentages, dollar amounts, time saved) to bullet points",
                    "Higher recruiter engagement and profile ranking in search results",
                ),
                "action_verbs": (
                    "experience bullet openings",
                    "Start each bullet with a strong action verb (Led, Developed, Implemented, etc.)",
                    "Improved readability and keyword indexing by LinkedIn's search",
                ),
                "role_alignment": (
                    "experience descriptions",
                    "Align job descriptions with your target role by emphasizing relevant responsibilities",
                    "Better matching with job recommendations and recruiter searches",
                ),
                "formatting_consistency": (
                    "experience formatting",
                    "Use consistent bullet-point formatting across all experience entries",
                    "Professional appearance and easier scanning by recruiters",
                ),
            },
            "skills": {
                "role_alignment": (
                    "skills list",
                    "Add skills that directly align with your target role and remove irrelevant ones",
                    "Higher visibility in recruiter searches for your target positions",
                ),
                "endorsement_count": (
                    "skill endorsements",
                    "Request endorsements from colleagues for your top skills",
                    "Skills with endorsements rank higher in LinkedIn's visibility",
                ),
                "top_skills_match": (
                    "top 3 pinned skills",
                    "Pin the 3 most relevant skills for your target role at the top",
                    "Maximum visibility for your core competencies in profile visits",
                ),
            },
            "posts": {
                "engagement_rate": (
                    "post engagement",
                    "Create content that drives more reactions and comments through questions and storytelling",
                    "Higher engagement signals thought leadership to LinkedIn's algorithm",
                ),
                "posting_frequency": (
                    "posting schedule",
                    "Increase posting frequency to at least 2-3 times per week for optimal visibility",
                    "Consistent posting increases reach by up to 50% per LinkedIn data",
                ),
                "topic_consistency": (
                    "post topics",
                    "Focus posts on 2-3 core topics aligned with your professional expertise",
                    "Builds topical authority which LinkedIn rewards with increased distribution",
                ),
            },
            "banner_photo": {
                "custom_banner": (
                    "profile banner",
                    "Upload a custom banner image that reflects your professional brand",
                    "Profiles with custom banners appear more professional and trustworthy",
                ),
                "photo_quality": (
                    "profile photo",
                    "Upload a high-resolution professional headshot (minimum 400x400 pixels)",
                    "High-quality photos increase profile view duration and connection acceptance",
                ),
                "brand_alignment": (
                    "visual branding",
                    "Ensure banner and photo visually align with your professional brand keywords",
                    "Consistent visual branding reinforces professional identity",
                ),
            },
        }

        section_details = details_map.get(section_name, {})
        if factor_name in section_details:
            return section_details[factor_name]

        # Default fallback
        return (
            f"{section_name} - {factor_name}",
            f"Improve the {factor_name.replace('_', ' ')} aspect of your {section_name}",
            "Better overall profile optimization score",
        )

    def _extract_section_content(self, profile: ProfileData) -> dict[str, str]:
        """Extract section content from ProfileData as strings for scoring.

        Args:
            profile: The profile data.

        Returns:
            Dictionary mapping section names to string content.
        """
        content_map: dict[str, str] = {}

        # Headline
        content_map["headline"] = profile.headline or ""

        # About
        content_map["about"] = profile.about or ""

        # Experience - serialize to string representation
        if profile.experience:
            exp_parts = []
            for exp in profile.experience:
                title = exp.get("title", "")
                company = exp.get("company", "")
                desc = exp.get("description", "")
                exp_parts.append(f"{title} at {company}\n{desc}")
            content_map["experience"] = "\n\n".join(exp_parts)
        else:
            content_map["experience"] = ""

        # Skills - serialize to string representation
        if profile.skills:
            skills_parts = []
            for skill in profile.skills:
                name = skill.get("name", "")
                endorsements = skill.get("endorsements", 0)
                skills_parts.append(f"{name} (endorsements: {endorsements})")
            content_map["skills"] = ", ".join(skills_parts)
        else:
            content_map["skills"] = ""

        # Posts - serialize to string representation
        if profile.posts:
            content_map["posts"] = json.dumps(profile.posts)
        else:
            content_map["posts"] = ""

        # Banner and Photo combined
        banner_photo_parts = []
        if profile.banner_url:
            banner_photo_parts.append(f"banner: {profile.banner_url}")
        if profile.photo_url:
            banner_photo_parts.append(f"photo: {profile.photo_url}")
        content_map["banner_photo"] = ", ".join(banner_photo_parts) if banner_photo_parts else ""

        return content_map

    def _build_github_summary(self, github: GitHubData) -> str:
        """Build a text summary of GitHub data for the report.

        Args:
            github: The GitHub data.

        Returns:
            A human-readable summary string.
        """
        parts: list[str] = []

        # Notable repos
        if github.notable_repos:
            parts.append(f"{len(github.notable_repos)} notable repos")

        # Primary languages
        if github.languages:
            top_languages = sorted(
                github.languages.items(), key=lambda x: x[1], reverse=True
            )[:3]
            lang_str = "/".join(lang for lang, _ in top_languages)
            parts.append(f"primary: {lang_str}")

        # Contribution frequency
        if github.contributions and github.contributions.commits_per_week_avg > 0:
            parts.append(
                f"{github.contributions.commits_per_week_avg:.0f} commits/week avg"
            )

        # Total repos
        if github.repos:
            parts.append(f"{len(github.repos)} total repos")

        return ", ".join(parts) if parts else "GitHub data available but no notable activity detected"
