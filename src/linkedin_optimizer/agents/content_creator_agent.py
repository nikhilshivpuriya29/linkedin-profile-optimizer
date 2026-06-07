"""Content Creator Agent for generating optimized LinkedIn profile content."""

import json
import logging
from datetime import datetime
from typing import Optional

from linkedin_optimizer.integrations.hf_client import HuggingFaceClient
from linkedin_optimizer.models import (
    AboutSuggestion,
    BannerSuggestion,
    ContentPackage,
    ExperienceSuggestion,
    GitHubData,
    HeadlineSuggestion,
    OptimizationReport,
    PostIdea,
    ProfileData,
    SectionInsight,
)

logger = logging.getLogger(__name__)

# Action verbs for experience bullet generation
ACTION_VERBS = [
    "Led",
    "Developed",
    "Built",
    "Designed",
    "Implemented",
    "Managed",
    "Created",
    "Delivered",
    "Improved",
    "Reduced",
    "Increased",
    "Launched",
    "Orchestrated",
    "Optimized",
    "Drove",
    "Spearheaded",
    "Architected",
    "Streamlined",
    "Automated",
    "Scaled",
]

# Post formats for idea generation
POST_FORMATS = ["text", "carousel", "poll", "video"]

# Default professional color palettes
DEFAULT_COLOR_PALETTES = [
    ["#0077B5", "#1DA1F2", "#FFFFFF", "#2E3440", "#88C0D0"],
    ["#0A66C2", "#2867B2", "#F5F5F5", "#1B1F23", "#56CCF2"],
    ["#003366", "#4A90D9", "#FFFFFF", "#333333", "#6FCF97"],
    ["#1B3A5C", "#5B9BD5", "#F0F4F8", "#2C3E50", "#48BB78"],
]


class ContentCreatorAgent:
    """Generates optimized content based on Optimization Report.

    Works both WITH an HF client (AI generation) and WITHOUT one
    (template-based generation for testing and resilience).

    Implements Requirements 4.1-4.8, 7.3.
    """

    def __init__(
        self,
        model_id: str,
        fallback_model_id: str,
        hf_client: Optional[HuggingFaceClient] = None,
    ) -> None:
        """Initialize the ContentCreatorAgent.

        Args:
            model_id: Primary Hugging Face model ID for content generation.
            fallback_model_id: Fallback model ID if primary is unavailable.
            hf_client: HuggingFaceClient instance for AI generation.
                       If None, template-based generation will be used.
        """
        self.model_id = model_id
        self.fallback_model_id = fallback_model_id
        self.hf_client = hf_client

    async def generate(
        self,
        report: OptimizationReport,
        profile: ProfileData,
        github: Optional[GitHubData] = None,
    ) -> ContentPackage:
        """Generate content for all sections scoring below 70.

        Per Req 4.1: generate content only for sections below 70.
        Always generates post ideas and banner if any section qualifies.

        Args:
            report: The optimization report with section scores.
            profile: The user's current profile data.
            github: Optional GitHub data for enrichment.

        Returns:
            A ContentPackage with all generated content.
        """
        # Find sections scoring below 70 (Req 4.1)
        low_scoring_sections = {
            section.section_name
            for section in report.sections
            if section.overall_score < 70
        }

        if not low_scoring_sections:
            return ContentPackage(generated_at=datetime.now().isoformat())

        # Build section-to-insight mapping
        insight_map: dict[str, SectionInsight] = {
            insight.section_name: insight for insight in report.insights
        }

        package = ContentPackage(generated_at=datetime.now().isoformat())

        # Generate headline if it scored below 70 (Req 4.2)
        if "headline" in low_scoring_sections:
            headline_insight = insight_map.get("headline")
            if headline_insight:
                package.headline = await self.generate_headline(
                    profile, headline_insight
                )

        # Generate about if it scored below 70 (Req 4.3)
        if "about" in low_scoring_sections:
            about_insight = insight_map.get("about")
            if about_insight:
                package.about = await self.generate_about(profile, about_insight)

        # Generate experience if it scored below 70 (Req 4.4)
        if "experience" in low_scoring_sections:
            experience_insight = insight_map.get("experience")
            if experience_insight:
                package.experience = await self.generate_experience(
                    profile, experience_insight, github
                )

        # Always generate post ideas and banner if any section qualifies (Req 4.5, 4.6)
        # Use the first available insight for context
        context_insight = next(
            (insight_map.get(s) for s in low_scoring_sections if s in insight_map),
            None,
        )
        if context_insight:
            package.post_ideas = await self.generate_post_ideas(
                profile, context_insight
            )
            package.banner = await self.generate_banner(profile, context_insight)

        return package

    async def generate_headline(
        self, profile: ProfileData, insights: SectionInsight
    ) -> HeadlineSuggestion:
        """Generate optimized headline within 220 char limit.

        Req 4.2: ≥2 keywords, value proposition, ≤220 chars.
        Req 4.7: Base content on user's existing language and domain.

        Args:
            profile: The user's current profile data.
            insights: Insights for the headline section.

        Returns:
            HeadlineSuggestion with optimized headline text.
        """
        # Attempt AI generation if client is available
        if self.hf_client is not None:
            try:
                return await self._ai_generate_headline(profile, insights)
            except Exception as e:
                logger.warning(
                    "AI headline generation failed: %s. Using template.", e
                )

        # Template-based generation
        return self._template_generate_headline(profile)

    async def generate_about(
        self, profile: ProfileData, insights: SectionInsight
    ) -> AboutSuggestion:
        """Generate optimized about section within 2600 char limit.

        Req 4.3: narrative hook, ≥3 keywords, CTA, ≤2600 chars.
        Req 4.7: Base content on user's existing language and domain.

        Args:
            profile: The user's current profile data.
            insights: Insights for the about section.

        Returns:
            AboutSuggestion with optimized about text.
        """
        if self.hf_client is not None:
            try:
                return await self._ai_generate_about(profile, insights)
            except Exception as e:
                logger.warning(
                    "AI about generation failed: %s. Using template.", e
                )

        return self._template_generate_about(profile)

    async def generate_experience(
        self,
        profile: ProfileData,
        insights: SectionInsight,
        github: Optional[GitHubData] = None,
    ) -> list[ExperienceSuggestion]:
        """Generate optimized experience descriptions.

        Req 4.4: action verbs, metrics, ≤2000 chars/position.
        Req 4.8: qualitative impact when metrics unavailable.
        Req 7.3: incorporate up to 5 GitHub achievements.

        Args:
            profile: The user's current profile data.
            insights: Insights for the experience section.
            github: Optional GitHub data for enrichment.

        Returns:
            List of ExperienceSuggestion for each position.
        """
        if self.hf_client is not None:
            try:
                return await self._ai_generate_experience(
                    profile, insights, github
                )
            except Exception as e:
                logger.warning(
                    "AI experience generation failed: %s. Using template.", e
                )

        return self._template_generate_experience(profile, github)

    async def generate_post_ideas(
        self, profile: ProfileData, insights: SectionInsight
    ) -> list[PostIdea]:
        """Generate at least 3 post ideas.

        Req 4.5: ≥3 ideas with topic, format, outline (≥2 sentences each).
        Req 4.7: Based on user's expertise and target audience.

        Args:
            profile: The user's current profile data.
            insights: Insights from analysis for context.

        Returns:
            List of at least 3 PostIdea objects.
        """
        if self.hf_client is not None:
            try:
                return await self._ai_generate_post_ideas(profile, insights)
            except Exception as e:
                logger.warning(
                    "AI post ideas generation failed: %s. Using template.", e
                )

        return self._template_generate_post_ideas(profile)

    async def generate_banner(
        self, profile: ProfileData, insights: SectionInsight
    ) -> BannerSuggestion:
        """Generate banner design suggestions.

        Req 4.6: dimensions, ≤5 colors, tagline ≤10 words.

        Args:
            profile: The user's current profile data.
            insights: Insights from analysis for context.

        Returns:
            BannerSuggestion with design specifications.
        """
        if self.hf_client is not None:
            try:
                return await self._ai_generate_banner(profile, insights)
            except Exception as e:
                logger.warning(
                    "AI banner generation failed: %s. Using template.", e
                )

        return self._template_generate_banner(profile)

    async def revise_suggestion(
        self, original: str, feedback: str, section_name: str
    ) -> str:
        """Revise a suggestion based on user feedback.

        Req 5.5: revise based on feedback (max 500 chars output).

        Args:
            original: The original content suggestion.
            feedback: User's feedback (max 500 chars).
            section_name: The section being revised.

        Returns:
            Revised content string (max 500 chars).
        """
        if self.hf_client is not None:
            try:
                return await self._ai_revise_suggestion(
                    original, feedback, section_name
                )
            except Exception as e:
                logger.warning(
                    "AI revision failed: %s. Using template revision.", e
                )

        return self._template_revise_suggestion(original, feedback, section_name)

    # -------------------------------------------------------------------------
    # AI-powered generation methods
    # -------------------------------------------------------------------------

    async def _ai_generate_headline(
        self, profile: ProfileData, insights: SectionInsight
    ) -> HeadlineSuggestion:
        """Generate headline using AI model."""
        keywords = self._extract_keywords(profile)
        prompt = (
            f"Generate an optimized LinkedIn headline for a professional.\n"
            f"Current headline: {profile.headline}\n"
            f"Skills: {', '.join(k['name'] for k in profile.skills[:10])}\n"
            f"Keywords to include: {', '.join(keywords[:5])}\n"
            f"Weaknesses to address: {', '.join(insights.weaknesses[:3])}\n\n"
            f"Requirements:\n"
            f"- Maximum 220 characters\n"
            f"- Include at least 2 relevant keywords\n"
            f"- Include a value proposition\n"
            f"- Base on user's existing domain\n\n"
            f"Return JSON: {{\"headline\": \"...\", \"keywords_used\": [...], \"value_proposition\": \"...\"}}"
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a LinkedIn profile optimization expert specializing in headline optimization.",
            max_tokens=512,
            temperature=0.7,
        )

        return self._parse_headline_response(response.text, profile)

    async def _ai_generate_about(
        self, profile: ProfileData, insights: SectionInsight
    ) -> AboutSuggestion:
        """Generate about section using AI model."""
        keywords = self._extract_keywords(profile)
        prompt = (
            f"Generate an optimized LinkedIn About section.\n"
            f"Current about: {profile.about[:500]}\n"
            f"Headline: {profile.headline}\n"
            f"Skills: {', '.join(k['name'] for k in profile.skills[:10])}\n"
            f"Weaknesses to address: {', '.join(insights.weaknesses[:3])}\n\n"
            f"Requirements:\n"
            f"- Maximum 2600 characters\n"
            f"- Start with a narrative hook\n"
            f"- Include at least 3 keywords: {', '.join(keywords[:5])}\n"
            f"- End with a call-to-action\n"
            f"- Use user's existing language and domain\n\n"
            f"Return JSON: {{\"text\": \"...\", \"hook_sentence\": \"...\", "
            f"\"keywords_used\": [...], \"call_to_action\": \"...\"}}"
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a LinkedIn profile optimization expert specializing in About section storytelling.",
            max_tokens=2048,
            temperature=0.7,
        )

        return self._parse_about_response(response.text, profile)

    async def _ai_generate_experience(
        self,
        profile: ProfileData,
        insights: SectionInsight,
        github: Optional[GitHubData],
    ) -> list[ExperienceSuggestion]:
        """Generate experience descriptions using AI model."""
        github_achievements = self._get_github_achievements(github)
        prompt = (
            f"Generate optimized LinkedIn experience descriptions.\n"
            f"Current experience: {json.dumps(profile.experience[:3])}\n"
            f"GitHub achievements to incorporate (up to 5): {json.dumps(github_achievements)}\n"
            f"Weaknesses: {', '.join(insights.weaknesses[:3])}\n\n"
            f"Requirements:\n"
            f"- Start each bullet with action verb\n"
            f"- Include metrics where possible\n"
            f"- Maximum 2000 characters per position\n"
            f"- If metrics unavailable, use qualitative impact\n"
            f"- Incorporate GitHub achievements naturally\n\n"
            f"Return JSON array of: {{\"role_title\": \"...\", \"company\": \"...\", "
            f"\"bullets\": [...], \"metrics_included\": bool, \"qualitative_note\": \"...\"}}"
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a LinkedIn profile expert specializing in experience optimization with quantifiable impact.",
            max_tokens=2048,
            temperature=0.7,
        )

        return self._parse_experience_response(response.text, profile, github)

    async def _ai_generate_post_ideas(
        self, profile: ProfileData, insights: SectionInsight
    ) -> list[PostIdea]:
        """Generate post ideas using AI model."""
        prompt = (
            f"Generate LinkedIn post ideas for a professional.\n"
            f"Headline: {profile.headline}\n"
            f"Skills: {', '.join(k['name'] for k in profile.skills[:10])}\n"
            f"Domain expertise from about: {profile.about[:200]}\n\n"
            f"Requirements:\n"
            f"- Generate at least 3 post ideas\n"
            f"- Each must have topic, format (text/carousel/poll/video), and outline\n"
            f"- Outline must be at least 2 sentences\n"
            f"- Base on user's expertise and audience\n\n"
            f"Return JSON array: [{{\"topic\": \"...\", \"format\": \"...\", \"content_outline\": \"...\"}}]"
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a LinkedIn content strategist specializing in engagement-optimized posts.",
            max_tokens=1024,
            temperature=0.8,
        )

        return self._parse_post_ideas_response(response.text, profile)

    async def _ai_generate_banner(
        self, profile: ProfileData, insights: SectionInsight
    ) -> BannerSuggestion:
        """Generate banner suggestion using AI model."""
        prompt = (
            f"Generate LinkedIn banner design suggestions.\n"
            f"Headline: {profile.headline}\n"
            f"Professional domain: {', '.join(k['name'] for k in profile.skills[:5])}\n\n"
            f"Requirements:\n"
            f"- Dimensions: 1584x396\n"
            f"- Color palette: up to 5 hex colors\n"
            f"- Tagline: max 10 words summarizing professional focus\n\n"
            f"Return JSON: {{\"dimensions\": \"...\", \"color_palette\": [...], \"tagline\": \"...\"}}"
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a visual branding expert for LinkedIn profiles.",
            max_tokens=512,
            temperature=0.7,
        )

        return self._parse_banner_response(response.text, profile)

    async def _ai_revise_suggestion(
        self, original: str, feedback: str, section_name: str
    ) -> str:
        """Revise content using AI model."""
        prompt = (
            f"Revise this LinkedIn {section_name} content based on user feedback.\n\n"
            f"Original content:\n{original}\n\n"
            f"User feedback:\n{feedback}\n\n"
            f"Requirements:\n"
            f"- Incorporate the feedback\n"
            f"- Keep within 500 characters\n"
            f"- Maintain professional tone\n"
            f"- Preserve the user's domain language\n\n"
            f"Return only the revised text, no JSON wrapper."
        )

        response = await self.hf_client.generate(  # type: ignore[union-attr]
            prompt=prompt,
            system_context="You are a LinkedIn content editor revising content based on user feedback.",
            max_tokens=512,
            temperature=0.5,
        )

        revised = response.text.strip()
        # Enforce 500 char limit
        return revised[:500]

    # -------------------------------------------------------------------------
    # Template-based (heuristic) generation methods
    # -------------------------------------------------------------------------

    def _template_generate_headline(self, profile: ProfileData) -> HeadlineSuggestion:
        """Generate headline using template-based approach.

        Extracts keywords from profile, builds headline with value proposition.
        Ensures ≤220 chars and ≥2 keywords.
        """
        keywords = self._extract_keywords(profile)

        # Extract role from current headline or experience
        role = self._extract_role(profile)

        # Build value proposition from experience
        value_prop = self._build_value_proposition(profile)

        # Construct headline: Role | Value Proposition | Keywords
        keyword_part = " | ".join(keywords[:2]) if len(keywords) >= 2 else ""
        if keyword_part:
            headline = f"{role} | {value_prop} | {keyword_part}"
        else:
            headline = f"{role} | {value_prop}"

        # Ensure ≤220 chars
        if len(headline) > 220:
            headline = f"{role} | {value_prop}"
        if len(headline) > 220:
            headline = headline[:217] + "..."

        # Ensure at least 2 keywords
        keywords_used = [k for k in keywords if k.lower() in headline.lower()]
        if len(keywords_used) < 2 and keywords:
            # Add keywords to make it at least 2
            remaining_space = 220 - len(headline)
            for kw in keywords:
                if kw.lower() not in headline.lower() and remaining_space > len(kw) + 3:
                    headline = f"{headline} | {kw}"
                    keywords_used.append(kw)
                    remaining_space = 220 - len(headline)
                if len(keywords_used) >= 2:
                    break

        # Final truncation
        headline = headline[:220]

        return HeadlineSuggestion(
            text=headline,
            keywords_used=keywords_used[:5],
            value_proposition=value_prop,
        )

    def _template_generate_about(self, profile: ProfileData) -> AboutSuggestion:
        """Generate about section using template-based approach.

        Builds narrative with hook, keywords from skills/experience, CTA.
        Ensures ≤2600 chars and ≥3 keywords.
        """
        keywords = self._extract_keywords(profile)
        role = self._extract_role(profile)

        # Build hook sentence
        hook = f"Passionate {role} dedicated to delivering impactful solutions that drive measurable results."

        # Build body paragraphs from experience and skills
        skills_text = ", ".join(k["name"] for k in profile.skills[:8]) if profile.skills else "various technologies"
        experience_summary = self._summarize_experience(profile)

        body = (
            f"\n\n{experience_summary}\n\n"
            f"My expertise spans {skills_text}, and I'm constantly exploring "
            f"new approaches to solve complex challenges in my domain."
        )

        # Build CTA
        cta = "Let's connect to discuss how we can collaborate and drive innovation together."

        # Combine ensuring ≥3 keywords are present
        full_text = f"{hook}{body}\n\n{cta}"

        # Ensure keywords are present
        keywords_used = [k for k in keywords if k.lower() in full_text.lower()]
        if len(keywords_used) < 3:
            # Inject additional keywords naturally
            additional_keywords = [k for k in keywords if k not in keywords_used]
            if additional_keywords:
                keyword_sentence = f"\n\nKey areas of focus: {', '.join(additional_keywords[:5])}."
                full_text = f"{hook}{body}\n\n{keyword_sentence}\n\n{cta}"
                keywords_used = [k for k in keywords if k.lower() in full_text.lower()]

        # Ensure ≤2600 chars
        full_text = full_text[:2600]

        return AboutSuggestion(
            text=full_text,
            hook_sentence=hook,
            keywords_used=keywords_used[:6],
            call_to_action=cta,
        )

    def _template_generate_experience(
        self, profile: ProfileData, github: Optional[GitHubData] = None
    ) -> list[ExperienceSuggestion]:
        """Generate experience descriptions using template-based approach.

        Uses action verbs, incorporates up to 5 GitHub achievements,
        ≤2000 chars/position. Handles missing metrics with qualitative impact.
        """
        suggestions: list[ExperienceSuggestion] = []
        github_achievements = self._get_github_achievements(github)
        github_idx = 0

        for exp in profile.experience[:5]:  # Limit to 5 positions
            role_title = exp.get("title", "Professional")
            company = exp.get("company", "Company")
            description = exp.get("description", "")

            # Check if metrics exist
            has_metrics = any(c.isdigit() for c in description) if description else False

            # Generate bullets with action verbs
            bullets = self._generate_experience_bullets(
                role_title, company, description, has_metrics
            )

            # Incorporate GitHub achievement if available (up to 5 total, Req 7.3)
            if github_idx < len(github_achievements) and github_idx < 5:
                achievement = github_achievements[github_idx]
                bullets.append(
                    f"Contributed to open-source project '{achievement}' demonstrating technical leadership"
                )
                github_idx += 1

            # Ensure total ≤2000 chars per position
            total_text = "\n".join(bullets)
            if len(total_text) > 2000:
                # Trim bullets to fit
                trimmed_bullets: list[str] = []
                current_len = 0
                for bullet in bullets:
                    if current_len + len(bullet) + 1 <= 2000:
                        trimmed_bullets.append(bullet)
                        current_len += len(bullet) + 1
                    else:
                        break
                bullets = trimmed_bullets

            # Handle missing metrics (Req 4.8)
            qualitative_note: Optional[str] = None
            if not has_metrics:
                qualitative_note = (
                    "Consider adding specific numbers (percentages, team sizes, "
                    "revenue impact) to strengthen these descriptions."
                )

            suggestions.append(
                ExperienceSuggestion(
                    role_title=role_title,
                    company=company,
                    bullets=bullets,
                    metrics_included=has_metrics,
                    qualitative_note=qualitative_note,
                )
            )

        return suggestions

    def _template_generate_post_ideas(self, profile: ProfileData) -> list[PostIdea]:
        """Generate at least 3 post ideas based on profile skills/experience.

        Each idea has topic, format, and outline (≥2 sentences).
        """
        skills = [k["name"] for k in profile.skills[:8]] if profile.skills else ["professional development"]
        role = self._extract_role(profile)

        ideas: list[PostIdea] = []

        # Idea 1: Technical lessons learned
        topic_1 = f"Lessons learned from my journey as a {role}"
        outline_1 = (
            f"Share key insights and turning points from your career as a {role}. "
            f"Highlight specific challenges you overcame and the skills that helped you succeed."
        )
        ideas.append(PostIdea(topic=topic_1, format="carousel", content_outline=outline_1))

        # Idea 2: Skill-based thought leadership
        primary_skill = skills[0] if skills else "technology"
        topic_2 = f"Top trends in {primary_skill} that professionals should watch"
        outline_2 = (
            f"Discuss emerging trends in {primary_skill} and how they impact the industry. "
            f"Provide actionable advice for professionals looking to stay ahead of the curve."
        )
        ideas.append(PostIdea(topic=topic_2, format="text", content_outline=outline_2))

        # Idea 3: Day-in-the-life or behind-the-scenes
        topic_3 = f"A day in the life of a {role}: what they don't tell you"
        outline_3 = (
            f"Give your audience a behind-the-scenes look at your daily workflow and responsibilities. "
            f"Share unexpected challenges and rewarding moments that define the role."
        )
        ideas.append(PostIdea(topic=topic_3, format="video", content_outline=outline_3))

        # Idea 4: Poll-based engagement
        if len(skills) >= 2:
            topic_4 = f"Which skill is more valuable in 2025: {skills[0]} or {skills[1]}?"
            outline_4 = (
                f"Create an engaging poll asking your network to weigh in on skill priorities. "
                f"Follow up with a comment sharing your own perspective and reasoning."
            )
            ideas.append(PostIdea(topic=topic_4, format="poll", content_outline=outline_4))

        return ideas

    def _template_generate_banner(self, profile: ProfileData) -> BannerSuggestion:
        """Generate banner suggestion with dimensions, colors, and tagline.

        Dimensions: 1584x396, ≤5 colors, tagline ≤10 words.
        """
        role = self._extract_role(profile)

        # Build tagline from role (max 10 words)
        tagline_parts = role.split()
        if len(tagline_parts) <= 8:
            tagline = f"{role} | Building the Future"
        else:
            tagline = " ".join(tagline_parts[:8]) + " Expert"

        # Ensure tagline is ≤10 words
        tagline_words = tagline.split()
        if len(tagline_words) > 10:
            tagline = " ".join(tagline_words[:10])

        # Select color palette based on domain
        color_palette = DEFAULT_COLOR_PALETTES[0][:5]

        return BannerSuggestion(
            dimensions="1584x396",
            color_palette=color_palette,
            tagline=tagline,
        )

    def _template_revise_suggestion(
        self, original: str, feedback: str, section_name: str
    ) -> str:
        """Revise content based on user feedback using templates.

        Simple approach: incorporate feedback keywords into the original.
        """
        # Extract key action words from feedback
        feedback_lower = feedback.lower()

        revised = original

        # Common revision patterns
        if "shorter" in feedback_lower or "concise" in feedback_lower:
            # Shorten the content
            words = original.split()
            revised = " ".join(words[: max(len(words) // 2, 10)])
        elif "longer" in feedback_lower or "more detail" in feedback_lower:
            # Add more context
            revised = f"{original} This demonstrates a commitment to excellence and continuous improvement in the {section_name} domain."
        elif "tone" in feedback_lower or "professional" in feedback_lower:
            # Make more professional
            revised = original.replace("!", ".").replace("awesome", "excellent")
        else:
            # Generic revision: append feedback context
            revised = f"{original} (Revised to incorporate: {feedback[:100]})"

        # Enforce 500 char limit
        return revised[:500]

    # -------------------------------------------------------------------------
    # AI response parsing methods
    # -------------------------------------------------------------------------

    def _parse_headline_response(
        self, response_text: str, profile: ProfileData
    ) -> HeadlineSuggestion:
        """Parse AI response for headline generation. Falls back to template."""
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                text = data.get("headline", "")[:220]
                keywords_used = data.get("keywords_used", [])
                value_prop = data.get("value_proposition", "")

                if text and len(keywords_used) >= 2:
                    return HeadlineSuggestion(
                        text=text,
                        keywords_used=keywords_used,
                        value_proposition=value_prop,
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return self._template_generate_headline(profile)

    def _parse_about_response(
        self, response_text: str, profile: ProfileData
    ) -> AboutSuggestion:
        """Parse AI response for about generation. Falls back to template."""
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                text = data.get("text", "")[:2600]
                hook = data.get("hook_sentence", "")
                keywords_used = data.get("keywords_used", [])
                cta = data.get("call_to_action", "")

                if text and len(keywords_used) >= 3:
                    return AboutSuggestion(
                        text=text,
                        hook_sentence=hook,
                        keywords_used=keywords_used,
                        call_to_action=cta,
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return self._template_generate_about(profile)

    def _parse_experience_response(
        self,
        response_text: str,
        profile: ProfileData,
        github: Optional[GitHubData],
    ) -> list[ExperienceSuggestion]:
        """Parse AI response for experience generation. Falls back to template."""
        try:
            json_start = response_text.find("[")
            json_end = response_text.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                suggestions = []
                for item in data:
                    bullets = item.get("bullets", [])
                    # Ensure ≤2000 chars per position
                    total = "\n".join(bullets)
                    if len(total) > 2000:
                        total = total[:2000]
                        bullets = total.split("\n")
                    suggestions.append(
                        ExperienceSuggestion(
                            role_title=item.get("role_title", ""),
                            company=item.get("company", ""),
                            bullets=bullets,
                            metrics_included=item.get("metrics_included", False),
                            qualitative_note=item.get("qualitative_note"),
                        )
                    )
                if suggestions:
                    return suggestions
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return self._template_generate_experience(profile, github)

    def _parse_post_ideas_response(
        self, response_text: str, profile: ProfileData
    ) -> list[PostIdea]:
        """Parse AI response for post ideas. Falls back to template."""
        try:
            json_start = response_text.find("[")
            json_end = response_text.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                ideas = []
                for item in data:
                    topic = item.get("topic", "")
                    fmt = item.get("format", "text")
                    outline = item.get("content_outline", "")
                    if topic and outline:
                        ideas.append(
                            PostIdea(
                                topic=topic,
                                format=fmt,
                                content_outline=outline,
                            )
                        )
                if len(ideas) >= 3:
                    return ideas
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return self._template_generate_post_ideas(profile)

    def _parse_banner_response(
        self, response_text: str, profile: ProfileData
    ) -> BannerSuggestion:
        """Parse AI response for banner suggestion. Falls back to template."""
        try:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                dimensions = data.get("dimensions", "1584x396")
                colors = data.get("color_palette", [])[:5]
                tagline = data.get("tagline", "")

                # Enforce constraints
                tagline_words = tagline.split()
                if len(tagline_words) > 10:
                    tagline = " ".join(tagline_words[:10])

                if dimensions and colors and tagline:
                    return BannerSuggestion(
                        dimensions=dimensions,
                        color_palette=colors,
                        tagline=tagline,
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

        return self._template_generate_banner(profile)

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    def _extract_keywords(self, profile: ProfileData) -> list[str]:
        """Extract relevant keywords from the profile.

        Combines skill names, headline words, and experience titles.
        """
        keywords: list[str] = []

        # From skills
        for skill in profile.skills[:10]:
            name = skill.get("name", "")
            if name and name not in keywords:
                keywords.append(name)

        # From headline
        if profile.headline:
            headline_words = [
                w.strip(".,|!?;:()")
                for w in profile.headline.split()
                if len(w.strip(".,|!?;:()")) > 3
            ]
            for word in headline_words[:5]:
                if word not in keywords and word.lower() not in [k.lower() for k in keywords]:
                    keywords.append(word)

        # From experience titles
        for exp in profile.experience[:3]:
            title = exp.get("title", "")
            if title:
                title_words = [
                    w.strip(".,|!?;:()")
                    for w in title.split()
                    if len(w.strip(".,|!?;:()")) > 3
                ]
                for word in title_words[:3]:
                    if word not in keywords and word.lower() not in [k.lower() for k in keywords]:
                        keywords.append(word)

        return keywords[:10]

    def _extract_role(self, profile: ProfileData) -> str:
        """Extract the primary professional role from the profile."""
        # Try headline first
        if profile.headline:
            # Take the first segment before | or at
            parts = profile.headline.split("|")
            role = parts[0].strip()
            # Remove "at Company" if present
            if " at " in role:
                role = role.split(" at ")[0].strip()
            if role:
                return role

        # Try first experience entry
        if profile.experience:
            title = profile.experience[0].get("title", "")
            if title:
                return title

        return "Professional"

    def _build_value_proposition(self, profile: ProfileData) -> str:
        """Build a value proposition from profile data."""
        if profile.experience:
            first_exp = profile.experience[0]
            description = first_exp.get("description", "")
            if description:
                # Extract a short impactful phrase
                sentences = description.split(".")
                for sentence in sentences:
                    if any(
                        word in sentence.lower()
                        for word in ["improved", "increased", "reduced", "delivered", "built", "led"]
                    ):
                        clean = sentence.strip()
                        if len(clean) > 5:
                            return clean[:80]

        # Fallback to skills-based proposition
        if profile.skills:
            top_skills = [k["name"] for k in profile.skills[:3]]
            return f"Delivering excellence in {', '.join(top_skills)}"

        return "Driving results through innovation"

    def _summarize_experience(self, profile: ProfileData) -> str:
        """Create a brief summary of professional experience."""
        if not profile.experience:
            return "With years of professional experience, I bring a unique perspective to every challenge."

        exp_count = len(profile.experience)
        latest_role = profile.experience[0].get("title", "professional")
        latest_company = profile.experience[0].get("company", "")

        summary = f"With {exp_count} roles across my career, including my current position as {latest_role}"
        if latest_company:
            summary += f" at {latest_company}"
        summary += ", I've developed deep expertise in solving complex challenges and delivering measurable outcomes."

        return summary

    def _get_github_achievements(
        self, github: Optional[GitHubData]
    ) -> list[str]:
        """Extract up to 5 GitHub achievements for content enrichment.

        Req 7.3: incorporate up to 5 GitHub-derived technical achievements.
        """
        if not github:
            return []

        achievements: list[str] = []

        # Notable repos (5+ stars or pinned)
        for repo in github.notable_repos[:5]:
            desc = repo.description or repo.name
            if repo.stars >= 5:
                achievements.append(
                    f"{repo.name} ({repo.stars} stars) - {desc}"
                )
            else:
                achievements.append(f"{repo.name} (pinned) - {desc}")

            if len(achievements) >= 5:
                break

        return achievements[:5]

    def _generate_experience_bullets(
        self,
        role_title: str,
        company: str,
        description: str,
        has_metrics: bool,
    ) -> list[str]:
        """Generate action-verb-led bullet points for an experience entry."""
        bullets: list[str] = []

        if description:
            # Parse existing description into lines
            lines = [l.strip() for l in description.split("\n") if l.strip()]
            verb_idx = 0

            for line in lines[:5]:
                # Clean bullet markers
                clean_line = line.lstrip("•-* ")
                # Ensure starts with action verb
                starts_with_action = any(
                    clean_line.lower().startswith(v.lower()) for v in ACTION_VERBS
                )
                if starts_with_action:
                    bullets.append(clean_line)
                else:
                    verb = ACTION_VERBS[verb_idx % len(ACTION_VERBS)]
                    verb_idx += 1
                    bullets.append(f"{verb} {clean_line[0].lower()}{clean_line[1:]}" if clean_line else f"{verb} initiatives at {company}")
        else:
            # Generate from scratch if no description
            bullets = [
                f"{ACTION_VERBS[0]} key initiatives as {role_title} at {company}",
                f"{ACTION_VERBS[1]} solutions that enhanced team productivity and delivery quality",
                f"{ACTION_VERBS[8]} processes to drive operational efficiency and stakeholder satisfaction",
            ]

        # Add qualitative impact if no metrics (Req 4.8)
        if not has_metrics and bullets:
            bullets[-1] = bullets[-1].rstrip(".")
            if "impact" not in bullets[-1].lower():
                bullets.append(
                    f"{ACTION_VERBS[2]} significant positive impact on team outcomes and project delivery"
                )

        return bullets
