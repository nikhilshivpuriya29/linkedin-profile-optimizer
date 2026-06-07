"""
LinkedIn Profile Optimizer — API Backend
==========================================
FastAPI server that powers the Next.js frontend.

Run with: python api.py
Serves at: http://localhost:8000
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

sys.path.insert(0, str(Path(__file__).parent / "src"))

from linkedin_optimizer.models import ProfileData, GitHubData
from linkedin_optimizer.agents.analyzer_agent import AnalyzerAgent
from linkedin_optimizer.agents.content_creator_agent import ContentCreatorAgent
from linkedin_optimizer.scrapers.github_extractor import GitHubExtractor
from linkedin_optimizer.persistence.data_store import DataStore

app = FastAPI(title="LinkedIn Profile Optimizer API", version="1.0.0")

# Allow frontend to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

@app.get("/")
async def serve_frontend():
    return FileResponse("web/static/index.html")


# ─── Response Models ─────────────────────────────────────────────────────────

class SectionScoreResponse(BaseModel):
    section_name: str
    overall_score: int
    missing: bool = False
    factors: list[dict] = []

class RecommendationResponse(BaseModel):
    element: str
    modification: str
    priority: str
    guideline_reference: str

class AnalysisResponse(BaseModel):
    overall_score: int
    sections: list[SectionScoreResponse]
    recommendations: list[RecommendationResponse]
    headline_current: str
    headline_suggested: Optional[str] = None
    about_current: str
    about_suggested: Optional[str] = None
    experience_current: list[dict] = []
    experience_suggested: list[dict] = []
    skills: list[str] = []
    certifications: list[str] = []
    post_ideas: list[dict] = []
    banner_suggestion: Optional[dict] = None
    github_summary: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None

class ChatResponse(BaseModel):
    reply: str


# ─── State ───────────────────────────────────────────────────────────────────

last_profile: Optional[ProfileData] = None
last_report = None
last_content = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

def parse_resume_pdf(file_path: str) -> ProfileData:
    """Parse resume PDF into ProfileData."""
    import fitz

    doc = fitz.open(file_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    doc.close()

    lines = [l.strip() for l in full_text.split("\n") if l.strip()]
    name = lines[0] if lines else "Professional"

    experience = []
    skills_list = []
    education = []
    certifications = []
    about_lines = []
    current_section = None
    current_job = None

    for line in lines[1:]:
        lower = line.lower()
        if any(kw in lower for kw in ["professional summary", "summary", "about"]):
            current_section = "about"
            continue
        elif any(kw in lower for kw in ["professional experience", "work experience", "experience"]):
            current_section = "experience"
            continue
        elif any(kw in lower for kw in ["technical skills", "skills"]):
            current_section = "skills"
            continue
        elif "education" in lower:
            current_section = "education"
            continue
        elif "certification" in lower:
            current_section = "certifications"
            continue

        if current_section == "about":
            about_lines.append(line)
        elif current_section == "experience":
            if line.startswith(("•", "-", "*", "–")):
                bullet = line.lstrip("•-*– ").strip()
                if bullet and current_job:
                    current_job["description"] = current_job.get("description", "") + "\n• " + bullet
            elif len(line) > 10 and not line.startswith(("•", "-")):
                if current_job:
                    experience.append(current_job)
                current_job = {"title": line, "company": "", "description": ""}
            elif current_job and not current_job.get("company"):
                current_job["company"] = line
        elif current_section == "skills":
            for chunk in line.replace("•", "").replace("-", "").replace("–", "").split(","):
                skill = chunk.strip()
                if skill and 2 < len(skill) < 60:
                    skills_list.append({"name": skill, "endorsements": 0})
        elif current_section == "certifications":
            cert = line.lstrip("•-*– ").strip()
            if cert and len(cert) > 3:
                certifications.append({"name": cert})

    if current_job:
        experience.append(current_job)

    headline = name
    if experience:
        title = experience[0].get("title", "")
        company = experience[0].get("company", "")
        if title:
            headline = f"{title}" + (f" at {company}" if company else "")

    return ProfileData(
        headline=headline,
        about=" ".join(about_lines),
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


async def fetch_github(url: str) -> Optional[GitHubData]:
    """Fetch GitHub data."""
    if not url.strip():
        return None

    username = url.strip().rstrip("/")
    if "github.com/" in username:
        username = username.split("github.com/")[-1].split("/")[0]

    try:
        import httpx

        async def patched_extract(self):
            async with httpx.AsyncClient(
                base_url="https://api.github.com",
                timeout=httpx.Timeout(15, connect=15),
                headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "linkedin-optimizer"},
                verify=False,
            ) as client:
                self._client = client
                return await asyncio.wait_for(self._extract_all(), timeout=30.0)

        original = GitHubExtractor.extract
        GitHubExtractor.extract = patched_extract
        extractor = GitHubExtractor(username=username, timeout=15)
        result = await extractor.extract()
        GitHubExtractor.extract = original

        if result.success and result.data:
            return result.data
    except Exception:
        pass
    return None


# ─── API Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(
    resume: Optional[UploadFile] = File(None),
    github_url: str = Form(""),
    linkedin_url: str = Form(""),
):
    """Run full profile analysis from resume PDF and/or GitHub."""
    global last_profile, last_report, last_content

    profile = None

    # Parse resume
    if resume:
        tmp_path = f"/tmp/resume_{datetime.now().strftime('%H%M%S')}.pdf"
        content = await resume.read()
        with open(tmp_path, "wb") as f:
            f.write(content)
        profile = parse_resume_pdf(tmp_path)
        os.unlink(tmp_path)

    # Try LinkedIn URL extraction if no resume
    if not profile and linkedin_url.strip():
        try:
            from linkedin_optimizer.scrapers.linkedin_mcp_client import LinkedInMCPClient
            from linkedin_optimizer.scrapers.profile_scraper import ProfileScraper

            mcp_client = LinkedInMCPClient({})
            scraper = ProfileScraper(mcp_client, max_retries=2)
            result = await scraper.extract(linkedin_url.strip())
            if result.success and result.profile_data:
                profile = result.profile_data
        except Exception:
            # MCP server not available — use LinkedIn URL as context hint
            pass

    if not profile:
        # If we only have LinkedIn URL but couldn't scrape, create minimal profile
        if linkedin_url.strip():
            # Extract username from URL for display
            username = linkedin_url.strip().rstrip("/").split("/")[-1]
            profile = ProfileData(
                headline=f"LinkedIn user: {username}",
                about="Profile data could not be extracted. Please upload your resume PDF for full analysis, or set up LinkedIn OAuth (see docs).",
            )
        else:
            profile = ProfileData(headline="No profile data provided. Please upload a resume PDF or provide your LinkedIn URL.")

    last_profile = profile

    # GitHub
    github_data = await fetch_github(github_url)

    # Analyze
    analyzer = AnalyzerAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    report = await analyzer.analyze(profile, github_data)
    last_report = report

    # Generate content
    content_creator = ContentCreatorAgent(
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        fallback_model_id="google/gemma-2-9b-it",
        hf_client=None,
    )
    content = await content_creator.generate(report, profile, github_data)
    last_content = content

    # Save
    data_store = DataStore("./data")
    run_id = f"run_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    data_store.save_profile_snapshot(profile, run_id)
    data_store.save_optimization_report(report, run_id)
    data_store.save_content_package(content, run_id)

    # Build response
    sections = [
        SectionScoreResponse(
            section_name=s.section_name,
            overall_score=s.overall_score,
            missing=s.missing,
            factors=[{"name": f.factor_name, "score": f.score, "explanation": f.explanation} for f in s.factor_scores],
        )
        for s in report.sections
    ]

    recommendations = []
    for insight in report.insights:
        for rec in insight.recommendations:
            recommendations.append(RecommendationResponse(
                element=rec.element,
                modification=rec.modification,
                priority=rec.priority.value,
                guideline_reference=rec.guideline_reference,
            ))

    experience_suggested = []
    for exp in (content.experience or []):
        experience_suggested.append({
            "role_title": exp.role_title,
            "company": exp.company,
            "bullets": exp.bullets,
        })

    post_ideas = []
    for idea in (content.post_ideas or []):
        post_ideas.append({
            "topic": idea.topic,
            "format": idea.format,
            "outline": idea.content_outline,
        })

    return AnalysisResponse(
        overall_score=report.overall_score,
        sections=sections,
        recommendations=recommendations,
        headline_current=profile.headline,
        headline_suggested=content.headline.text if content.headline else None,
        about_current=profile.about,
        about_suggested=content.about.text if content.about else None,
        experience_current=profile.experience,
        experience_suggested=experience_suggested,
        skills=[s.get("name", "") for s in profile.skills],
        certifications=[c.get("name", "") for c in (profile.certifications or [])],
        post_ideas=post_ideas,
        banner_suggestion={
            "dimensions": content.banner.dimensions,
            "colors": content.banner.color_palette,
            "tagline": content.banner.tagline,
        } if content.banner else None,
        github_summary=report.github_summary,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat endpoint for profile optimization questions."""
    global last_profile, last_report, last_content

    msg = request.message.lower()

    if not last_profile:
        return ChatResponse(reply="Please run an analysis first by uploading your resume.")

    if any(kw in msg for kw in ["headline", "title"]):
        current = last_profile.headline
        suggested = last_content.headline.text if last_content and last_content.headline else "N/A"
        reply = f"**Current:** {current}\n\n**Suggested:** {suggested}\n\nThe improved headline uses more of the 220-character limit, includes keywords, and adds a value proposition. Want me to try a different angle?"

    elif any(kw in msg for kw in ["about", "summary", "bio"]):
        if last_content and last_content.about:
            reply = f"**Suggested About section:**\n\n{last_content.about.text}\n\n---\n**Hook:** {last_content.about.hook_sentence}\n**CTA:** {last_content.about.call_to_action}"
        else:
            reply = "Your about section scored well. Consider adding a hook and CTA."

    elif any(kw in msg for kw in ["post", "content", "write"]):
        if last_content and last_content.post_ideas:
            ideas = "\n".join(f"- **{p.topic}** ({p.format}): {p.content_outline[:80]}..." for p in last_content.post_ideas[:4])
            reply = f"**Post ideas for you:**\n\n{ideas}\n\nWant me to expand any of these?"
        else:
            reply = "Start posting 2-3x/week. Best topics: lessons learned, how-tos, industry trends."

    elif any(kw in msg for kw in ["score", "rating", "how"]):
        if last_report:
            lines = "\n".join(f"- {s.section_name.title()}: {s.overall_score}/100" for s in last_report.sections)
            reply = f"**Your scores:**\n\n{lines}\n\n**Overall: {last_report.overall_score}/100**"
        else:
            reply = "Run analysis first."

    else:
        reply = "I can help with: headline, about section, experience bullets, post ideas, skills, banner. What would you like to improve?"

    return ChatResponse(reply=reply)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
