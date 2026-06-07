"""
LinkedIn Profile Optimizer — Web UI
====================================
A simple browser-based interface for the LinkedIn Profile Optimizer.

Run with: python app.py
Opens at: http://localhost:7860
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).parent / "src"))

from linkedin_optimizer.models import (
    ProfileData,
    GitHubData,
    OptimizationReport,
    ContentPackage,
)
from linkedin_optimizer.agents.analyzer_agent import AnalyzerAgent
from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent
from linkedin_optimizer.scrapers.github_extractor import GitHubExtractor
from linkedin_optimizer.persistence.data_store import DataStore


# ─── Helper Functions ────────────────────────────────────────────────────────


def parse_resume_text(resume_text: str) -> ProfileData:
    """Parse pasted resume/profile text into ProfileData."""
    lines = [l.strip() for l in resume_text.strip().split("\n") if l.strip()]

    # Try to extract headline (first meaningful line)
    headline = lines[0] if lines else "Professional"

    # Use the full text as about if short, or extract sections
    about = resume_text[:2000] if len(resume_text) < 2500 else ""

    # Look for experience-like patterns
    experience = []
    skills_list = []

    current_section = None
    for line in lines:
        lower = line.lower()
        if any(kw in lower for kw in ["experience", "work history", "employment"]):
            current_section = "experience"
            continue
        elif any(kw in lower for kw in ["skills", "technical skills", "technologies"]):
            current_section = "skills"
            continue
        elif any(kw in lower for kw in ["education", "certifications", "cert"]):
            current_section = "other"
            continue

        if current_section == "experience" and line.startswith(("•", "-", "*", "–")):
            experience.append({"description": line.lstrip("•-*– ")})
        elif current_section == "skills":
            # Split comma-separated skills
            for skill in line.replace("•", "").replace("-", "").split(","):
                skill = skill.strip()
                if skill and len(skill) < 50:
                    skills_list.append({"name": skill, "endorsements": 0})

    return ProfileData(
        headline=headline,
        about=about if about else resume_text[:500],
        experience=experience[:10],
        skills=skills_list[:15],
        endorsements=[],
        posts=[],
        banner_url=None,
        photo_url=None,
        education=[],
        certifications=[],
        follower_count=0,
        connection_count=0,
        profile_views=None,
    )


def build_profile_from_fields(
    headline: str, about: str, experience: str, skills: str, github_username: str
) -> ProfileData:
    """Build ProfileData from individual form fields."""
    # Parse experience bullets
    exp_list = []
    if experience.strip():
        for bullet in experience.strip().split("\n"):
            bullet = bullet.strip().lstrip("•-*– ")
            if bullet:
                exp_list.append({"description": bullet})

    # Parse skills
    skills_list = []
    if skills.strip():
        for skill in skills.replace("\n", ",").split(","):
            skill = skill.strip()
            if skill:
                skills_list.append({"name": skill, "endorsements": 0})

    return ProfileData(
        headline=headline,
        about=about,
        experience=exp_list,
        skills=skills_list,
        endorsements=[],
        posts=[],
        banner_url=None,
        photo_url=None,
        education=[],
        certifications=[],
        follower_count=0,
        connection_count=0,
        profile_views=None,
    )


async def fetch_github(username: str) -> tuple[GitHubData | None, str]:
    """Fetch GitHub data with SSL bypass for corporate networks."""
    if not username.strip():
        return None, "No GitHub username provided"

    try:
        import httpx

        async def patched_extract(self):
            try:
                async with httpx.AsyncClient(
                    base_url="https://api.github.com",
                    timeout=httpx.Timeout(15, connect=15),
                    headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "linkedin-optimizer"},
                    verify=False,
                ) as client:
                    self._client = client
                    return await asyncio.wait_for(self._extract_all(), timeout=30.0)
            except Exception as e:
                from linkedin_optimizer.models import GitHubExtractionResult
                return GitHubExtractionResult(success=False, data=None, error_message=str(e))

        original = GitHubExtractor.extract
        GitHubExtractor.extract = patched_extract
        extractor = GitHubExtractor(username=username.strip(), timeout=15)
        result = await extractor.extract()
        GitHubExtractor.extract = original

        if result.success and result.data:
            langs = ", ".join(f"{k}({v})" for k, v in list(result.data.languages.items())[:5])
            msg = f"✅ {len(result.data.repos)} repos | Languages: {langs}"
            return result.data, msg
        else:
            return None, f"⚠️ {result.error_message}"
    except Exception as e:
        return None, f"❌ Error: {str(e)}"


async def run_analysis(
    headline: str, about: str, experience: str, skills: str, github_username: str
) -> tuple[str, str, str, str, str]:
    """Run the full analysis pipeline and return formatted results."""

    # Build profile
    profile = build_profile_from_fields(headline, about, experience, skills, github_username)

    # Fetch GitHub
    github_data, github_msg = await fetch_github(github_username)

    # Analyze
    analyzer = AnalyzerAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    report = await analyzer.analyze(profile, github_data)

    # Generate content
    content_creator = ContentCreatorAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    content = await content_creator.generate(report, profile, github_data)

    # Save results
    data_store = DataStore("./data")
    run_id = f"run_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    data_store.save_profile_snapshot(profile, run_id)
    data_store.save_optimization_report(report, run_id)
    data_store.save_content_package(content, run_id)

    # Format scores
    scores_md = f"## 📊 Overall Score: {report.overall_score}/100\n\n"
    scores_md += "| Section | Score | Status |\n|---------|-------|--------|\n"
    for s in report.sections:
        if s.missing:
            status = "⬜ Missing"
        elif s.overall_score >= 70:
            status = "🟢 Good"
        elif s.overall_score >= 50:
            status = "🟡 Needs Work"
        else:
            status = "🔴 Low"
        scores_md += f"| {s.section_name.title()} | {s.overall_score} | {status} |\n"

    # Format recommendations
    recs_md = "## 💡 Top Recommendations\n\n"
    for insight in report.insights:
        for rec in insight.recommendations[:2]:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            e = emoji.get(rec.priority.value, "⚪")
            recs_md += f"{e} **{rec.priority.value.upper()}** — {rec.modification}\n\n"

    # Format suggested headline
    headline_md = ""
    if content.headline:
        headline_md = f"## ✨ Suggested Headline\n\n> {content.headline.text}\n\n"
        headline_md += f"**Keywords:** {', '.join(content.headline.keywords_used)}\n\n"
        headline_md += f"**Value Prop:** {content.headline.value_proposition}"

    # Format suggested about
    about_md = ""
    if content.about:
        about_md = f"## ✨ Suggested About Section\n\n{content.about.text}"

    # Format post ideas
    posts_md = ""
    if content.post_ideas:
        posts_md = "## 📝 Post Ideas\n\n"
        for i, idea in enumerate(content.post_ideas, 1):
            posts_md += f"### {i}. {idea.topic} ({idea.format})\n{idea.content_outline}\n\n"

    # Combine GitHub status
    status_msg = f"**GitHub:** {github_msg}\n\n**Run saved:** `{run_id}`"

    return scores_md, recs_md, headline_md, about_md, posts_md


def analyze_sync(headline, about, experience, skills, github_username):
    """Synchronous wrapper for async analysis."""
    return asyncio.run(run_analysis(headline, about, experience, skills, github_username))


# ─── Gradio UI ───────────────────────────────────────────────────────────────

THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
)

with gr.Blocks(
    title="LinkedIn Profile Optimizer",
) as app:

    gr.Markdown(
        """
        # 🚀 LinkedIn Profile Optimizer
        **AI-powered analysis and content generation for your LinkedIn profile**

        Paste your current profile content below, click "Analyze", and get instant optimization suggestions.
        No LinkedIn login required — everything runs locally on your machine.
        """,
        elem_classes=["main-header"],
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📝 Your Current Profile")

            headline_input = gr.Textbox(
                label="Headline",
                placeholder="e.g., Software Engineer at Google",
                lines=1,
            )
            about_input = gr.Textbox(
                label="About Section",
                placeholder="Paste your LinkedIn About section here...",
                lines=6,
            )
            experience_input = gr.Textbox(
                label="Experience (one bullet per line)",
                placeholder="• Led team of 5 engineers\n• Reduced deployment time by 70%\n• Built CI/CD pipeline",
                lines=6,
            )
            skills_input = gr.Textbox(
                label="Skills (comma-separated)",
                placeholder="Python, JavaScript, AWS, Docker, CI/CD",
                lines=2,
            )
            github_input = gr.Textbox(
                label="GitHub Username (optional)",
                placeholder="your-github-username",
                lines=1,
            )

            analyze_btn = gr.Button(
                "🔍 Analyze My Profile",
                variant="primary",
                size="lg",
            )

        with gr.Column(scale=1):
            gr.Markdown("### 📊 Results")

            scores_output = gr.Markdown(label="Scores")
            recs_output = gr.Markdown(label="Recommendations")

    gr.Markdown("---")
    gr.Markdown("### ✨ Generated Content")

    with gr.Row():
        with gr.Column():
            headline_output = gr.Markdown(label="Suggested Headline")
        with gr.Column():
            about_output = gr.Markdown(label="Suggested About")

    posts_output = gr.Markdown(label="Post Ideas")

    # Wire up the button
    analyze_btn.click(
        fn=analyze_sync,
        inputs=[headline_input, about_input, experience_input, skills_input, github_input],
        outputs=[scores_output, recs_output, headline_output, about_output, posts_output],
    )

    # Example profiles for quick testing
    gr.Examples(
        examples=[
            [
                "Salesforce Developer & DevOps Engineer at Gentrack Global",
                "Salesforce Developer and DevOps Engineer with 4+ years of experience. Strong expertise in Apex, LWC, Flows, and SOQL optimization.",
                "• Automated 100+ manual deployment steps, reducing effort by 70%\n• Built REST-based integrations with OAuth2.0\n• Authored Apex test classes achieving 90%+ coverage",
                "Apex, LWC, Salesforce DX, REST APIs, Git, CI/CD, SOQL, JavaScript",
                "nikhilshivpuriya29",
            ],
            [
                "Full Stack Developer",
                "I build web applications.",
                "• Built a React dashboard\n• Created REST APIs",
                "React, Node.js, Python, PostgreSQL",
                "",
            ],
        ],
        inputs=[headline_input, about_input, experience_input, skills_input, github_input],
    )

    gr.Markdown(
        """
        ---
        **How it works:** Your profile data is analyzed locally using AI scoring heuristics.
        Nothing is sent to LinkedIn. Results are saved in `./data/` for future reference.

        Made with ❤️ by [Nikhil Shivpuriya](https://github.com/nikhilshivpuriya29)
        """
    )


if __name__ == "__main__":
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=THEME,
        css="""
        .main-header { text-align: center; margin-bottom: 20px; }
        .score-panel { border-left: 4px solid #0077B5; padding-left: 16px; }
        """,
    )
