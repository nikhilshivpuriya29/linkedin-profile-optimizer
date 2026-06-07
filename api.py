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
    """AI-powered chat endpoint using OpenAI/Claude/HuggingFace."""
    global last_profile, last_report, last_content

    msg = request.message
    provider = (request.context or {}).get("provider", "builtin")  # openai, anthropic, huggingface, builtin
    api_key = (request.context or {}).get("api_key", "")

    # Build profile context for the AI
    profile_context = ""
    if last_profile:
        profile_context = f"""
Current LinkedIn Profile:
- Headline: {last_profile.headline}
- About: {last_profile.about[:300]}
- Skills: {', '.join(s.get('name','') for s in last_profile.skills[:10])}
- Experience: {len(last_profile.experience)} roles
"""
    if last_report:
        profile_context += f"\nProfile Score: {last_report.overall_score}/100"
        for s in last_report.sections:
            profile_context += f"\n- {s.section_name}: {s.overall_score}/100 {'(missing)' if s.missing else ''}"

    if last_content:
        if last_content.headline:
            profile_context += f"\n\nSuggested Headline: {last_content.headline.text}"
        if last_content.about:
            profile_context += f"\nSuggested About: {last_content.about.text[:200]}..."

    # System prompt for LinkedIn optimization expertise
    system_prompt = """You are an expert LinkedIn Profile Optimization Coach. You help professionals improve their LinkedIn profiles for maximum visibility, engagement, and career opportunities.

Your expertise includes:
- Writing compelling headlines (max 220 chars) with keywords and value propositions
- Crafting engaging About sections with narrative hooks, keywords, and CTAs
- Optimizing experience bullets with action verbs and metrics
- Recommending posting strategies for thought leadership
- LinkedIn algorithm knowledge (search ranking, content distribution)
- Professional branding and positioning

Rules:
- Always provide specific, actionable suggestions (not generic advice)
- Reference LinkedIn's algorithm and best practices when relevant
- Keep suggestions within LinkedIn's character limits
- Maintain the user's professional voice and domain expertise
- When suggesting content, make it ready to copy-paste
- If asked to rewrite something, provide the full rewritten version
- Be concise but thorough

"""
    if profile_context:
        system_prompt += f"\nUser's current profile data:\n{profile_context}"

    # Try AI providers
    try:
        if provider == "openai" and api_key:
            reply = await _call_openai(api_key, system_prompt, msg)
        elif provider == "anthropic" and api_key:
            reply = await _call_anthropic(api_key, system_prompt, msg)
        elif provider == "gemini" and api_key:
            reply = await _call_gemini(api_key, system_prompt, msg)
        elif provider == "huggingface" and api_key:
            reply = await _call_huggingface(api_key, system_prompt, msg)
        else:
            # Built-in responses (no API key needed)
            reply = _builtin_response(msg, last_profile, last_report, last_content)
    except Exception as e:
        reply = f"API Error: {str(e)[:200]}. Check your API key and try again."

    return ChatResponse(reply=reply)


async def _call_openai(api_key: str, system_prompt: str, message: str) -> str:
    """Call OpenAI GPT-4 for chat responses."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        max_tokens=1000,
        temperature=0.7,
    )
    return response.choices[0].message.content


async def _call_anthropic(api_key: str, system_prompt: str, message: str) -> str:
    """Call Claude for chat responses."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=system_prompt,
        messages=[{"role": "user", "content": message}],
    )
    return response.content[0].text


async def _call_huggingface(api_key: str, system_prompt: str, message: str) -> str:
    """Call HuggingFace Inference API for chat responses."""
    import httpx as _httpx

    full_prompt = f"[System]: {system_prompt}\n\n[User]: {message}\n\n[Assistant]:"
    async with _httpx.AsyncClient(verify=False, timeout=30.0) as client:
        r = await client.post(
            "https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.3",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"inputs": full_prompt, "parameters": {"max_new_tokens": 800, "temperature": 0.7}},
        )
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and data:
                return data[0].get("generated_text", "").replace(full_prompt, "").strip()
        return f"HuggingFace API error: {r.status_code}"


async def _call_gemini(api_key: str, system_prompt: str, message: str) -> str:
    """Call Google Gemini for chat responses."""
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"{system_prompt}\n\nUser: {message}",
    )
    return response.text


def _builtin_response(msg: str, profile, report, content) -> str:
    """Built-in responses when no AI API key is configured."""
    lower = msg.lower()

    if not profile:
        return "Please run an analysis first by uploading your resume, then I can help optimize your profile."

    if any(kw in lower for kw in ["headline", "title"]):
        current = profile.headline
        suggested = content.headline.text if content and content.headline else None
        if suggested:
            return f"**Current headline:** {current}\n\n**Optimized headline:**\n> {suggested}\n\n**Why it's better:**\n- Uses more of the 220-character limit\n- Includes searchable keywords\n- Has a value proposition\n\nWant a different angle? Tell me what to emphasize."
        return f"Your headline: \"{current}\"\n\nTo improve, add a value proposition and keywords. Example:\n> {current} | Delivering [result] through [expertise]"

    elif any(kw in lower for kw in ["about", "summary", "bio"]):
        if content and content.about:
            return f"**Optimized About section:**\n\n{content.about.text}\n\n---\n**Structure used:**\n- Hook: _{content.about.hook_sentence}_\n- Keywords: {', '.join(content.about.keywords_used)}\n- CTA: _{content.about.call_to_action}_"
        return "Your about section needs a narrative hook in the first line and a call-to-action at the end. Tell me your target audience and I'll draft one."

    elif any(kw in lower for kw in ["post", "content", "publish", "write"]):
        if content and content.post_ideas:
            ideas = "\n".join(f"{i+1}. **{p.topic}** ({p.format})\n   {p.content_outline}" for i, p in enumerate(content.post_ideas[:4]))
            return f"**Your personalized post ideas:**\n\n{ideas}\n\nWant me to expand any of these into a full draft?"
        return "Start posting 2-3x/week. Best formats: carousels (highest reach), polls (engagement), text posts (thought leadership)."

    elif any(kw in lower for kw in ["score", "rating", "analysis", "how am i"]):
        if report:
            lines = "\n".join(f"- **{s.section_name.title()}**: {s.overall_score}/100 {'🟢' if s.overall_score >= 70 else '🟡' if s.overall_score >= 50 else '🔴'}" for s in report.sections)
            return f"**Your profile scores:**\n\n{lines}\n\n**Overall: {report.overall_score}/100**\n\nFocus on the red sections first — they have the most improvement potential."
        return "Run analysis first to see scores."

    elif any(kw in lower for kw in ["experience", "bullet", "job", "work"]):
        if content and content.experience:
            exp = content.experience[0]
            bullets = "\n".join(f"• {b}" for b in exp.bullets[:4])
            return f"**Optimized bullets for {exp.role_title} at {exp.company}:**\n\n{bullets}\n\n**Tips applied:** Action verbs, quantifiable metrics, role-aligned keywords."
        return "For experience bullets: Start with action verbs (Led, Built, Drove), include metrics (%, $, time), align with your target role."

    elif any(kw in lower for kw in ["skill", "endorse"]):
        skills = ", ".join(s.get("name", "") for s in profile.skills[:8])
        return f"**Your skills:** {skills}\n\n**Action items:**\n1. Pin your top 3 role-relevant skills\n2. Ask 5 colleagues to endorse them this week\n3. Remove skills not related to your target role\n\nWhich role are you targeting?"

    elif any(kw in lower for kw in ["banner", "photo", "picture"]):
        return "**Profile visuals checklist:**\n\n📸 **Photo:** Professional headshot, 400x400px min, face fills 60% of frame\n\n🖼️ **Banner (1584×396px):** Use Canva → search 'LinkedIn banner' → add:\n- Your name + title\n- 2-3 key skills or certs\n- Professional color scheme\n\nThese alone can increase profile views 20-30%."

    elif any(kw in lower for kw in ["recommend", "suggestion", "fix", "improve"]):
        if report:
            recs = []
            for insight in report.insights:
                for rec in insight.recommendations[:2]:
                    recs.append(f"{'🔴' if rec.priority.value == 'high' else '🟡' if rec.priority.value == 'medium' else '🟢'} **{rec.priority.value.upper()}:** {rec.modification}")
            return "**Top recommendations:**\n\n" + "\n\n".join(recs[:8])
        return "Run analysis first to get personalized recommendations."

    else:
        return "I can help with:\n\n• **\"Improve my headline\"** — get an optimized headline\n• **\"Rewrite my about\"** — new about section with hook + CTA\n• **\"Post ideas\"** — content suggestions for this week\n• **\"Fix my experience\"** — better bullets with metrics\n• **\"My scores\"** — see section-by-section breakdown\n• **\"Banner tips\"** — visual branding suggestions\n\nWhat would you like to work on?"


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ─── Settings / API Key Storage ──────────────────────────────────────────────

class SettingsRequest(BaseModel):
    provider: str  # openai, anthropic, huggingface
    api_key: str
    linkedin_cookie: Optional[str] = None  # li_at cookie for session-based access

_settings = {"provider": "builtin", "api_key": "", "linkedin_cookie": ""}

@app.post("/api/settings")
async def save_settings(req: SettingsRequest):
    """Save user's AI provider settings and LinkedIn session."""
    global _settings
    _settings["provider"] = req.provider
    _settings["api_key"] = req.api_key
    if req.linkedin_cookie:
        _settings["linkedin_cookie"] = req.linkedin_cookie
    return {"status": "saved", "provider": req.provider}

@app.get("/api/settings")
async def get_settings():
    """Get current settings (masked key)."""
    key = _settings["api_key"]
    masked = key[:8] + "..." if len(key) > 8 else "not set"
    return {
        "provider": _settings["provider"],
        "api_key_masked": masked,
        "has_linkedin_cookie": bool(_settings.get("linkedin_cookie")),
    }


# ─── LinkedIn Session-Based Scraping ─────────────────────────────────────────

@app.post("/api/scrape-linkedin")
async def scrape_linkedin(linkedin_url: str = Form(""), cookie: str = Form("")):
    """Scrape LinkedIn profile using session cookie (li_at).

    Users can provide their LinkedIn li_at cookie from their browser
    to enable authenticated profile scraping without OAuth app setup.
    """
    import httpx as _httpx

    url = linkedin_url.strip()
    session_cookie = cookie.strip() or _settings.get("linkedin_cookie", "")

    if not url:
        return {"success": False, "error": "No LinkedIn URL provided"}

    if not session_cookie:
        return {
            "success": False,
            "error": "No LinkedIn session cookie. Go to linkedin.com while logged in → F12 → Application → Cookies → copy 'li_at' value → paste in Settings.",
        }

    # Extract username from URL
    username = url.rstrip("/").split("/in/")[-1].split("/")[0] if "/in/" in url else ""

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Cookie": f"li_at={session_cookie}",
            "Accept": "application/vnd.linkedin.normalized+json+2.1",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Use LinkedIn's Voyager API (internal API used by the frontend)
        api_url = f"https://www.linkedin.com/voyager/api/identity/profiles/{username}/profileView"

        async with _httpx.AsyncClient(verify=False, timeout=15.0) as client:
            r = await client.get(api_url, headers=headers)

        if r.status_code == 200:
            data = r.json()
            # Parse the Voyager response into our format
            profile_data = _parse_voyager_response(data, username)
            return {"success": True, "profile": profile_data}
        elif r.status_code == 401:
            return {"success": False, "error": "LinkedIn session expired. Please get a fresh li_at cookie."}
        elif r.status_code == 403:
            return {"success": False, "error": "Access denied. The li_at cookie may be invalid."}
        else:
            return {"success": False, "error": f"LinkedIn returned status {r.status_code}"}

    except Exception as e:
        return {"success": False, "error": f"Scraping failed: {str(e)[:200]}"}


def _parse_voyager_response(data: dict, username: str) -> dict:
    """Parse LinkedIn Voyager API response into profile data."""
    profile = {}

    try:
        # The response structure varies but typically has 'included' array
        included = data.get("included", [])

        for item in included:
            entity_type = item.get("$type", "")

            if "Profile" in entity_type and "firstName" in item:
                profile["headline"] = item.get("headline", "")
                profile["about"] = item.get("summary", "")
                profile["firstName"] = item.get("firstName", "")
                profile["lastName"] = item.get("lastName", "")
                profile["follower_count"] = item.get("followersCount", 0)

            elif "Position" in entity_type:
                if "experience" not in profile:
                    profile["experience"] = []
                profile["experience"].append({
                    "title": item.get("title", ""),
                    "company": item.get("companyName", ""),
                    "description": item.get("description", ""),
                })

            elif "Skill" in entity_type:
                if "skills" not in profile:
                    profile["skills"] = []
                name = item.get("name", "")
                if name:
                    profile["skills"].append({"name": name, "endorsements": 0})

    except Exception:
        pass

    if not profile.get("headline"):
        profile["headline"] = f"LinkedIn profile: {username}"

    return profile


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
