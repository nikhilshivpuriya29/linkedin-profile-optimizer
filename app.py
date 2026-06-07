"""
LinkedIn Profile Optimizer — Web UI
====================================
A beautiful browser-based interface that mimics LinkedIn's profile layout.

Features:
- Paste LinkedIn URL / Upload Resume PDF / Provide GitHub URL
- Shows CURRENT profile on the left, OPTIMIZED profile on the right
- Chat interface to refine suggestions interactively
- Full scoring report with section-by-section breakdown

Run with: python app.py
Opens at: http://localhost:7860
"""

import asyncio
import sys
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

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


# ─── State Management ────────────────────────────────────────────────────────

current_profile: Optional[ProfileData] = None
current_report: Optional[OptimizationReport] = None
current_content: Optional[ContentPackage] = None
current_github: Optional[GitHubData] = None


# ─── Resume PDF Parser ───────────────────────────────────────────────────────

def parse_resume_pdf(file_path: str) -> ProfileData:
    """Extract profile data from a resume PDF."""
    import fitz

    doc = fitz.open(file_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()

    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # Extract name as headline base
    name = lines[0] if lines else "Professional"

    # Find sections
    experience = []
    skills_list = []
    education = []
    certifications = []
    about_lines = []
    current_section = None
    current_job = None

    for line in lines[1:]:
        lower = line.lower()

        # Detect section headers
        if any(kw in lower for kw in ["professional summary", "summary", "about me", "objective"]):
            current_section = "about"
            continue
        elif any(kw in lower for kw in ["professional experience", "work experience", "experience", "employment"]):
            current_section = "experience"
            continue
        elif any(kw in lower for kw in ["technical skills", "skills", "technologies", "competencies"]):
            current_section = "skills"
            continue
        elif any(kw in lower for kw in ["education", "academic"]):
            current_section = "education"
            continue
        elif any(kw in lower for kw in ["certification", "certifications", "credentials"]):
            current_section = "certifications"
            continue

        # Parse content based on section
        if current_section == "about":
            about_lines.append(line)
        elif current_section == "experience":
            if line.startswith(("•", "-", "*", "–")):
                bullet = line.lstrip("•-*– ").strip()
                if bullet and current_job:
                    current_job["description"] = current_job.get("description", "") + "\n• " + bullet
            elif not line[0].isdigit() and len(line) > 10 and not line.startswith(("•", "-")):
                # Likely a job title or company line
                if current_job:
                    experience.append(current_job)
                current_job = {"title": line, "company": "", "description": ""}
            elif current_job and not current_job["company"]:
                current_job["company"] = line
        elif current_section == "skills":
            # Parse comma or newline separated skills
            for chunk in line.replace("•", "").replace("-", "").replace("–", "").split(","):
                skill = chunk.strip()
                if skill and 2 < len(skill) < 60:
                    skills_list.append({"name": skill, "endorsements": 0})
        elif current_section == "education":
            if line and len(line) > 5:
                education.append({"school": line})
        elif current_section == "certifications":
            cert = line.lstrip("•-*– ").strip()
            if cert and len(cert) > 3:
                certifications.append({"name": cert})

    if current_job:
        experience.append(current_job)

    about = " ".join(about_lines)

    # Build a headline from name + first job
    headline = name
    if experience:
        first_title = experience[0].get("title", "")
        first_company = experience[0].get("company", "")
        if first_title:
            headline = f"{first_title}"
            if first_company:
                headline += f" at {first_company}"

    return ProfileData(
        headline=headline,
        about=about,
        experience=experience[:10],
        skills=skills_list[:20],
        endorsements=[],
        posts=[],
        banner_url=None,
        photo_url=None,
        education=education,
        certifications=certifications,
        follower_count=0,
        connection_count=0,
        profile_views=None,
    )


# ─── GitHub Fetcher ──────────────────────────────────────────────────────────

async def fetch_github_data(github_url: str) -> tuple[Optional[GitHubData], str]:
    """Fetch GitHub data from URL or username."""
    if not github_url.strip():
        return None, ""

    # Extract username from URL or use as-is
    username = github_url.strip().rstrip("/")
    if "github.com/" in username:
        username = username.split("github.com/")[-1].split("/")[0]

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
        extractor = GitHubExtractor(username=username, timeout=15)
        result = await extractor.extract()
        GitHubExtractor.extract = original

        if result.success and result.data:
            langs = ", ".join(list(result.data.languages.keys())[:5])
            return result.data, f"✅ {len(result.data.repos)} repos · {langs}"
        else:
            return None, f"⚠️ {result.error_message}"
    except Exception as e:
        return None, f"❌ {str(e)[:100]}"


# ─── LinkedIn Profile Card Renderer ─────────────────────────────────────────

def render_profile_card(profile: ProfileData, label: str = "Current") -> str:
    """Render a LinkedIn-style profile card in HTML."""
    banner_color = "#0077B5" if label == "Current" else "#057642"

    # Experience HTML
    exp_html = ""
    for exp in profile.experience[:3]:
        title = exp.get("title", "Role")
        company = exp.get("company", "Company")
        duration = exp.get("duration", "")
        desc = exp.get("description", "")
        # Format bullets
        bullets = ""
        for line in desc.split("\n"):
            line = line.strip().lstrip("•-*– ")
            if line:
                bullets += f"<li>{line}</li>"

        exp_html += f"""
        <div style="margin-bottom: 16px; padding-bottom: 16px; border-bottom: 1px solid #e0e0e0;">
            <div style="font-weight: 600; font-size: 14px;">{title}</div>
            <div style="color: #666; font-size: 13px;">{company} · {duration}</div>
            <ul style="margin-top: 8px; padding-left: 20px; font-size: 13px; color: #333;">{bullets}</ul>
        </div>
        """

    # Skills HTML
    skills_html = ""
    for skill in profile.skills[:8]:
        name = skill.get("name", "")
        skills_html += f'<span style="display: inline-block; background: #f0f0f0; padding: 4px 12px; border-radius: 16px; margin: 3px; font-size: 12px;">{name}</span>'

    # Certifications
    certs_html = ""
    for cert in (profile.certifications or [])[:4]:
        name = cert.get("name", "")
        certs_html += f'<div style="font-size: 12px; color: #555; padding: 2px 0;">🏆 {name}</div>'

    card = f"""
    <div style="border: 1px solid #d0d0d0; border-radius: 12px; overflow: hidden; background: white; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 100%;">
        <!-- Banner -->
        <div style="height: 80px; background: linear-gradient(135deg, {banner_color}, #004182);"></div>

        <!-- Profile Header -->
        <div style="padding: 0 20px 16px;">
            <div style="width: 72px; height: 72px; border-radius: 50%; background: #e0e0e0; border: 3px solid white; margin-top: -36px; display: flex; align-items: center; justify-content: center; font-size: 28px;">👤</div>

            <h3 style="margin: 8px 0 4px; font-size: 18px; color: #191919;">{profile.headline or 'No headline set'}</h3>

            <div style="font-size: 12px; color: #666; margin-bottom: 12px;">
                {profile.follower_count} followers · {profile.connection_count} connections
            </div>
        </div>

        <!-- About -->
        <div style="padding: 16px 20px; border-top: 1px solid #e8e8e8;">
            <h4 style="margin: 0 0 8px; font-size: 15px; color: #191919;">About</h4>
            <p style="font-size: 13px; color: #333; line-height: 1.5; margin: 0;">{(profile.about or 'No about section')[:400]}{'...' if profile.about and len(profile.about) > 400 else ''}</p>
        </div>

        <!-- Experience -->
        <div style="padding: 16px 20px; border-top: 1px solid #e8e8e8;">
            <h4 style="margin: 0 0 12px; font-size: 15px; color: #191919;">Experience</h4>
            {exp_html if exp_html else '<p style="font-size: 13px; color: #999;">No experience listed</p>'}
        </div>

        <!-- Skills -->
        <div style="padding: 16px 20px; border-top: 1px solid #e8e8e8;">
            <h4 style="margin: 0 0 8px; font-size: 15px; color: #191919;">Skills</h4>
            <div>{skills_html if skills_html else '<p style="font-size: 13px; color: #999;">No skills listed</p>'}</div>
        </div>

        <!-- Certifications -->
        {'<div style="padding: 16px 20px; border-top: 1px solid #e8e8e8;"><h4 style="margin: 0 0 8px; font-size: 15px; color: #191919;">Certifications</h4>' + certs_html + '</div>' if certs_html else ''}
    </div>
    """
    return card


def render_optimized_card(profile: ProfileData, content: ContentPackage) -> str:
    """Render the optimized version as a LinkedIn-style card."""
    optimized = ProfileData(
        headline=content.headline.text if content.headline else profile.headline,
        about=content.about.text if content.about else profile.about,
        experience=profile.experience,
        skills=profile.skills,
        endorsements=profile.endorsements,
        posts=profile.posts,
        banner_url=profile.banner_url,
        photo_url=profile.photo_url,
        education=profile.education,
        certifications=profile.certifications,
        follower_count=profile.follower_count,
        connection_count=profile.connection_count,
        profile_views=profile.profile_views,
    )
    return render_profile_card(optimized, label="Optimized")


# ─── Score Badge Renderer ────────────────────────────────────────────────────

def render_score_report(report: OptimizationReport) -> str:
    """Render a visual score report."""
    html = f"""
    <div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea, #764ba2); border-radius: 12px; color: white; margin-bottom: 20px;">
        <div style="font-size: 48px; font-weight: bold;">{report.overall_score}</div>
        <div style="font-size: 14px; opacity: 0.9;">Overall Profile Score</div>
    </div>

    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 20px;">
    """

    for s in report.sections:
        if s.missing:
            color = "#999"
            bg = "#f5f5f5"
            icon = "⬜"
        elif s.overall_score >= 70:
            color = "#057642"
            bg = "#e8f5e9"
            icon = "🟢"
        elif s.overall_score >= 50:
            color = "#b45309"
            bg = "#fff3cd"
            icon = "🟡"
        else:
            color = "#cc1016"
            bg = "#fce4ec"
            icon = "🔴"

        html += f"""
        <div style="background: {bg}; padding: 12px; border-radius: 8px; text-align: center;">
            <div style="font-size: 20px;">{icon}</div>
            <div style="font-size: 22px; font-weight: bold; color: {color};">{s.overall_score}</div>
            <div style="font-size: 11px; color: #666; text-transform: capitalize;">{s.section_name.replace('_', ' ')}</div>
        </div>
        """

    html += "</div>"

    # Recommendations
    html += '<div style="background: #f8f9fa; border-radius: 8px; padding: 16px;">'
    html += '<h4 style="margin: 0 0 12px; font-size: 14px;">💡 Top Recommendations</h4>'

    for insight in report.insights:
        for rec in insight.recommendations[:2]:
            emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(rec.priority.value, "⚪")
            html += f'<div style="padding: 6px 0; font-size: 13px;">{emoji} <b>{rec.priority.value.upper()}</b> — {rec.modification}</div>'

    html += "</div>"
    return html


def render_post_ideas(content: ContentPackage) -> str:
    """Render post ideas."""
    if not content or not content.post_ideas:
        return "<p>No post ideas generated</p>"

    html = ""
    for i, idea in enumerate(content.post_ideas, 1):
        format_emoji = {"text": "📝", "carousel": "🎠", "poll": "📊", "video": "🎬"}.get(idea.format, "📌")
        html += f"""
        <div style="border: 1px solid #e0e0e0; border-radius: 8px; padding: 14px; margin-bottom: 10px; background: white;">
            <div style="font-weight: 600; font-size: 14px;">{format_emoji} {idea.topic}</div>
            <div style="font-size: 11px; color: #0077B5; margin: 4px 0;">Format: {idea.format.title()}</div>
            <div style="font-size: 13px; color: #555; margin-top: 6px;">{idea.content_outline}</div>
        </div>
        """
    return html


# ─── Main Analysis Function ──────────────────────────────────────────────────

async def analyze_async(
    linkedin_url: str,
    resume_file,
    github_url: str,
    progress=gr.Progress()
) -> tuple[str, str, str, str, str]:
    """Run full analysis from inputs."""
    global current_profile, current_report, current_content, current_github

    progress(0.1, desc="Preparing...")

    profile = None

    # Priority: Resume PDF > LinkedIn URL > empty
    if resume_file is not None:
        progress(0.2, desc="Parsing resume PDF...")
        profile = parse_resume_pdf(resume_file)
    elif linkedin_url.strip():
        progress(0.2, desc="Note: LinkedIn URL scraping requires OAuth. Using manual mode...")
        # For now, return instruction
        return (
            "<p style='padding:20px; color: #666;'>⚠️ LinkedIn URL scraping requires OAuth setup. Please upload your resume PDF instead, or paste your profile info in the Chat tab.</p>",
            "",
            "<p>Upload a resume PDF to get started</p>",
            "",
            "",
        )

    if profile is None:
        return (
            "<p style='padding: 20px; color: #999;'>Please upload a resume PDF or provide a LinkedIn URL.</p>",
            "", "", "", "",
        )

    current_profile = profile

    # GitHub
    progress(0.3, desc="Fetching GitHub data...")
    github_data, github_msg = await fetch_github_data(github_url)
    current_github = github_data

    # Analyze
    progress(0.5, desc="Analyzing profile sections...")
    analyzer = AnalyzerAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    report = await analyzer.analyze(profile, github_data)
    current_report = report

    # Generate content
    progress(0.7, desc="Generating optimized content...")
    content_creator = ContentCreatorAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    content = await content_creator.generate(report, profile, github_data)
    current_content = content

    # Save results
    progress(0.9, desc="Saving results...")
    data_store = DataStore("./data")
    run_id = f"run_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    data_store.save_profile_snapshot(profile, run_id)
    data_store.save_optimization_report(report, run_id)
    data_store.save_content_package(content, run_id)

    progress(1.0, desc="Done!")

    # Render outputs
    current_card = render_profile_card(profile, "Current")
    optimized_card = render_optimized_card(profile, content)
    score_html = render_score_report(report)
    posts_html = render_post_ideas(content)
    status = f"✅ Analysis complete · Score: {report.overall_score}/100"
    if github_msg:
        status += f" · GitHub: {github_msg}"

    return current_card, optimized_card, score_html, posts_html, status


def analyze_sync(linkedin_url, resume_file, github_url, progress=gr.Progress()):
    """Sync wrapper."""
    return asyncio.run(analyze_async(linkedin_url, resume_file, github_url, progress))


# ─── Chat Function ───────────────────────────────────────────────────────────

def chat_respond(message: str, history: list) -> tuple[list, str]:
    """Respond to chat messages about profile optimization."""
    global current_profile, current_report, current_content

    if not current_profile:
        response = "Please run an analysis first (upload your resume in the 'Analyze' tab), then come back here to chat about improvements."
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response})
        return history, ""

    # Build context-aware response
    lower_msg = message.lower()

    if any(kw in lower_msg for kw in ["headline", "title"]):
        if current_content and current_content.headline:
            response = f"""**Your current headline:** {current_profile.headline}

**Suggested improvement:**
> {current_content.headline.text}

**Why this works:**
- Keywords used: {', '.join(current_content.headline.keywords_used)}
- Value proposition: {current_content.headline.value_proposition}
- Uses more of the 220-character limit

Want me to make it shorter, add different keywords, or try a different angle?"""
        else:
            response = f"Your headline '{current_profile.headline}' scores well. To improve further, try adding a value proposition (what you deliver) and relevant keywords."

    elif any(kw in lower_msg for kw in ["about", "summary", "bio"]):
        if current_content and current_content.about:
            response = f"""**Suggested About section:**

{current_content.about.text[:600]}{'...' if len(current_content.about.text) > 600 else ''}

**Key elements:**
- Hook: _{current_content.about.hook_sentence}_
- Keywords: {', '.join(current_content.about.keywords_used)}
- CTA: _{current_content.about.call_to_action}_

Want me to adjust the tone, make it shorter, or focus on a different angle?"""
        else:
            response = "Your about section looks good! Consider adding a narrative hook in the first sentence and ending with a call-to-action."

    elif any(kw in lower_msg for kw in ["post", "content", "publish", "write"]):
        if current_content and current_content.post_ideas:
            ideas = "\n".join(f"{i+1}. **{p.topic}** ({p.format}) — {p.content_outline[:80]}..." for i, p in enumerate(current_content.post_ideas[:4]))
            response = f"""Here are your suggested post ideas:

{ideas}

Which one interests you? I can expand any of these into a full post draft."""
        else:
            response = "Start posting about your expertise 2-3 times per week. Topics that work: lessons learned, how-to guides, industry trends, day-in-the-life content."

    elif any(kw in lower_msg for kw in ["experience", "job", "work", "bullet"]):
        if current_content and current_content.experience:
            exp = current_content.experience[0]
            bullets = "\n".join(f"• {b}" for b in exp.bullets[:4])
            response = f"""**Suggested experience bullets for {exp.role_title} at {exp.company}:**

{bullets}

**Tips applied:**
- Action verbs at the start
- Quantifiable metrics where possible
- {'Has metrics ✅' if exp.metrics_included else '⚠️ Add specific numbers where you can'}

Want me to adjust these or generate for a different role?"""
        else:
            response = "Your experience bullets look decent. To improve: start each with an action verb (Led, Built, Designed) and include at least one metric per bullet (%, $, time saved)."

    elif any(kw in lower_msg for kw in ["score", "how", "rating", "analysis"]):
        if current_report:
            sections = "\n".join(f"- **{s.section_name.title()}**: {s.overall_score}/100 {'🟢' if s.overall_score >= 70 else '🟡' if s.overall_score >= 50 else '🔴'}" for s in current_report.sections)
            response = f"""**Your profile scores:**

{sections}

**Overall: {current_report.overall_score}/100**

Focus on the red/yellow sections first — they have the most room for improvement. Ask me about any specific section for detailed suggestions."""
        else:
            response = "Run the analysis first to see your scores."

    elif any(kw in lower_msg for kw in ["skill", "endorse"]):
        skills = ", ".join(s.get("name", "") for s in current_profile.skills[:8])
        response = f"""**Your current skills:** {skills}

**Recommendations:**
1. Pin your top 3 role-relevant skills
2. Ask 5 colleagues to endorse them
3. Remove skills not relevant to your target role
4. LinkedIn's algorithm shows endorsed skills more prominently

What role are you targeting? I can suggest which skills to pin."""

    elif any(kw in lower_msg for kw in ["banner", "photo", "picture", "image"]):
        response = """**Profile visual recommendations:**

🖼️ **Banner:** Create a custom banner (1584×396px) with:
- Your name + role
- 2-3 key skills/certifications
- Professional color scheme (#0077B5 LinkedIn blue works well)
- Use Canva (free) → search "LinkedIn banner"

📸 **Photo:** Upload a professional headshot (min 400×400px):
- Face takes up 60% of frame
- Neutral or branded background
- Good lighting, eye contact with camera

These two changes alone can increase profile views by 20-30%."""

    else:
        if current_report:
            weak = [s.section_name for s in current_report.sections if s.overall_score < 50 and not s.missing]
            response = f"""I can help you optimize any part of your profile. Try asking about:

- "Improve my headline"
- "Rewrite my about section"
- "Give me post ideas"
- "Fix my experience bullets"
- "What's my score?"
- "Banner suggestions"

{'Your weakest areas: **' + ', '.join(weak) + '** — want me to focus there?' if weak else ''}"""
        else:
            response = "Upload your resume in the 'Analyze' tab first, then come back here. I'll be able to give you specific suggestions based on your actual profile."

    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": response})
    return history, ""


# ─── Gradio UI ───────────────────────────────────────────────────────────────

CSS = """
.profile-card { border-radius: 12px; overflow: hidden; }
.score-panel { text-align: center; }
.tab-content { min-height: 500px; }
footer { display: none !important; }
"""

with gr.Blocks(title="LinkedIn Profile Optimizer") as app:

    gr.Markdown(
        """
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="margin: 0;">🚀 LinkedIn Profile Optimizer</h1>
            <p style="color: #666; margin-top: 8px;">Upload your resume → See your current vs optimized profile side-by-side → Chat to refine</p>
        </div>
        """
    )

    with gr.Tabs():
        # ─── TAB 1: ANALYZE ──────────────────────────────────────────
        with gr.Tab("📊 Analyze", id="analyze"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("### Input Your Profile")
                    linkedin_url = gr.Textbox(
                        label="LinkedIn Profile URL (optional)",
                        placeholder="https://www.linkedin.com/in/your-username",
                        lines=1,
                    )
                    resume_upload = gr.File(
                        label="📄 Upload Resume PDF (recommended)",
                        file_types=[".pdf"],
                        type="filepath",
                    )
                    github_url = gr.Textbox(
                        label="GitHub URL or Username (optional)",
                        placeholder="https://github.com/username or just username",
                        lines=1,
                    )
                    analyze_btn = gr.Button("🔍 Analyze My Profile", variant="primary", size="lg")
                    status_output = gr.Markdown("")

                with gr.Column(scale=1):
                    gr.Markdown("### 📈 Score Report")
                    score_output = gr.HTML("")

            gr.Markdown("---")
            gr.Markdown("### 👤 Current Profile → ✨ Optimized Profile")
            gr.Markdown("*See exactly how your profile looks now vs. how it could look*")

            with gr.Row(equal_height=True):
                with gr.Column(scale=1):
                    gr.Markdown("#### 👈 Current")
                    current_card_output = gr.HTML("<p style='text-align:center; padding: 40px; color: #999;'>Upload your resume to see your current profile</p>")

                with gr.Column(scale=1):
                    gr.Markdown("#### 👉 Optimized")
                    optimized_card_output = gr.HTML("<p style='text-align:center; padding: 40px; color: #999;'>Optimized profile will appear here</p>")

            gr.Markdown("---")
            gr.Markdown("### 📝 Content Ideas")
            posts_output = gr.HTML("")

        # ─── TAB 2: CHAT ─────────────────────────────────────────────
        with gr.Tab("💬 Chat", id="chat"):
            gr.Markdown(
                """
                ### Ask me anything about your profile
                *Examples: "Improve my headline", "Write a post about CI/CD", "Make my about section shorter"*
                """
            )
            chatbot = gr.Chatbot(
                height=450,
                placeholder="Run analysis first, then ask me to refine any section...",
            )
            with gr.Row():
                chat_input = gr.Textbox(
                    placeholder="Ask about your headline, about, experience, posts...",
                    lines=1,
                    scale=6,
                    show_label=False,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)

            # Chat examples
            gr.Examples(
                examples=[
                    "Improve my headline",
                    "Rewrite my about section",
                    "Give me post ideas for this week",
                    "What's my weakest section?",
                    "Make my experience bullets more impactful",
                    "Banner design suggestions",
                ],
                inputs=chat_input,
            )

    # ─── Wire up events ──────────────────────────────────────────────

    analyze_btn.click(
        fn=analyze_sync,
        inputs=[linkedin_url, resume_upload, github_url],
        outputs=[current_card_output, optimized_card_output, score_output, posts_output, status_output],
    )

    chat_input.submit(
        fn=chat_respond,
        inputs=[chat_input, chatbot],
        outputs=[chatbot, chat_input],
    )
    send_btn.click(
        fn=chat_respond,
        inputs=[chat_input, chatbot],
        outputs=[chatbot, chat_input],
    )


if __name__ == "__main__":
    print("\n🚀 Starting LinkedIn Profile Optimizer UI...")
    print("   Open: http://localhost:7860\n")
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        css=CSS,
    )
