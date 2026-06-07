"""
LinkedIn Profile Optimizer — FastAPI Backend
Uses HuggingFace Router with Llama 3.3 70B for AI chat
"""

import os
from dotenv import load_dotenv
load_dotenv()

import json
import re
import httpx
import PyPDF2
import io
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(title="LinkedIn Profile Optimizer")

# ─── In-memory profile store ───────────────────────────────────────────────
profile_store = {
    "linkedin": None,
    "resume": None,
    "github": None,
    "analysis": None,
}

# ─── AI Configuration ──────────────────────────────────────────────────────
AI_ENDPOINT = "https://router.huggingface.co/together/v1/chat/completions"
AI_MODEL = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

SYSTEM_PROMPT = """You are "LinkBot" — a world-class LinkedIn Profile Optimization Coach with 10+ years of experience helping professionals maximize their LinkedIn presence.

Your personality:
- Direct and actionable (no fluff)
- You give specific copy-paste-ready text suggestions
- You reference LinkedIn's algorithm and best practices
- You're encouraging but honest about what needs improvement

Your expertise:
- LinkedIn SEO (keywords, search ranking)
- Headline optimization (220 chars, value props, keywords)
- About section writing (hooks, CTAs, narrative structure)
- Experience bullets (STAR method, metrics, action verbs)
- Content strategy (post topics, formats, frequency)
- Profile visuals (banner, photo best practices)
- Skills & endorsements optimization
- LinkedIn algorithm knowledge

Rules:
- Always provide specific text the user can copy-paste
- Keep character limits in mind (headline: 220, about: 2600)
- Reference LinkedIn data/research when possible
- If asked to rewrite, give the FULL rewritten version
- Be concise — max 200 words per response unless writing full sections
"""


def get_hf_token():
    return os.environ.get("HF_TOKEN", "")


# ─── LinkedIn Scraping ─────────────────────────────────────────────────────
async def scrape_linkedin(profile_url: str, li_at_cookie: str) -> dict:
    """Scrape LinkedIn profile using Voyager API"""
    # Extract username from URL
    username = profile_url.rstrip("/").split("/")[-1]
    if not username:
        return {"error": "Could not extract username from URL"}

    headers = {
        "csrf-token": "ajax:0",
        "x-restli-protocol-version": "2.0.0",
        "cookie": f"li_at={li_at_cookie}; JSESSIONID=\"ajax:0\"",
    }

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        # Get profile data
        try:
            resp = await client.get(
                f"https://www.linkedin.com/voyager/api/identity/dash/profiles?q=memberIdentity&memberIdentity={username}&decorationId=com.linkedin.voyager.dash.deco.identity.profile.WebProfileCardOverlay-75",
                headers=headers,
            )
            if resp.status_code != 200:
                # Try alternative endpoint
                resp = await client.get(
                    f"https://www.linkedin.com/voyager/api/identity/profiles/{username}/profileView",
                    headers=headers,
                )

            if resp.status_code == 200:
                data = resp.json()
            else:
                return {"error": f"LinkedIn API returned {resp.status_code}. Check your li_at cookie."}
        except Exception as e:
            return {"error": f"Failed to connect to LinkedIn: {str(e)}"}

        # Try to get full profile view
        try:
            profile_resp = await client.get(
                f"https://www.linkedin.com/voyager/api/identity/profiles/{username}/profileView",
                headers=headers,
            )
            if profile_resp.status_code == 200:
                profile_data = profile_resp.json()
            else:
                profile_data = data
        except:
            profile_data = data

        # Parse profile
        profile = parse_linkedin_profile(profile_data, username)
        return profile


def parse_linkedin_profile(data: dict, username: str) -> dict:
    """Parse LinkedIn Voyager API response into structured profile"""
    profile = {
        "username": username,
        "name": "",
        "headline": "",
        "about": "",
        "location": "",
        "connections": 0,
        "experience": [],
        "education": [],
        "skills": [],
        "certifications": [],
        "projects": [],
        "recommendations": 0,
    }

    try:
        # Try different data structures
        if "profile" in data:
            p = data["profile"]
            profile["name"] = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
            profile["headline"] = p.get("headline", "")
            profile["about"] = p.get("summary", "")
            profile["location"] = p.get("locationName", "")
        elif "elements" in data:
            elements = data["elements"]
            if elements:
                p = elements[0]
                profile["name"] = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
                profile["headline"] = p.get('headline', '')
                profile["about"] = p.get('summary', '')
        elif "included" in data:
            for item in data.get("included", []):
                if item.get("$type") == "com.linkedin.voyager.identity.profile.Profile":
                    profile["name"] = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
                    profile["headline"] = item.get("headline", "")
                    profile["about"] = item.get("summary", "")
                    profile["location"] = item.get("locationName", "")

        # Parse experience
        if "positionView" in data:
            positions = data["positionView"].get("elements", [])
            for pos in positions:
                profile["experience"].append({
                    "title": pos.get("title", ""),
                    "company": pos.get("companyName", ""),
                    "description": pos.get("description", ""),
                })
        elif "included" in data:
            for item in data.get("included", []):
                if item.get("$type", "").endswith("Position"):
                    profile["experience"].append({
                        "title": item.get("title", ""),
                        "company": item.get("companyName", ""),
                        "description": item.get("description", ""),
                    })

        # Parse education
        if "educationView" in data:
            education = data["educationView"].get("elements", [])
            for edu in education:
                profile["education"].append({
                    "school": edu.get("schoolName", ""),
                    "degree": edu.get("degreeName", ""),
                    "field": edu.get("fieldOfStudy", ""),
                })

        # Parse skills
        if "skillView" in data:
            skills = data["skillView"].get("elements", [])
            profile["skills"] = [s.get("name", "") for s in skills]

    except Exception as e:
        profile["parse_error"] = str(e)

    return profile


# ─── GitHub Scraping ───────────────────────────────────────────────────────
async def scrape_github(github_url: str) -> dict:
    """Scrape GitHub profile data"""
    # Extract username
    username = github_url.rstrip("/").split("/")[-1]
    if not username:
        return {"error": "Could not extract GitHub username"}

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        try:
            # Get user profile
            user_resp = await client.get(f"https://api.github.com/users/{username}")
            if user_resp.status_code != 200:
                return {"error": f"GitHub API returned {user_resp.status_code}"}
            user_data = user_resp.json()

            # Get repos
            repos_resp = await client.get(
                f"https://api.github.com/users/{username}/repos?sort=stars&per_page=10"
            )
            repos_data = repos_resp.json() if repos_resp.status_code == 200 else []

            return {
                "username": username,
                "name": user_data.get("name", ""),
                "bio": user_data.get("bio", ""),
                "public_repos": user_data.get("public_repos", 0),
                "followers": user_data.get("followers", 0),
                "following": user_data.get("following", 0),
                "company": user_data.get("company", ""),
                "blog": user_data.get("blog", ""),
                "top_repos": [
                    {
                        "name": r.get("name", ""),
                        "description": r.get("description", ""),
                        "stars": r.get("stargazers_count", 0),
                        "language": r.get("language", ""),
                        "forks": r.get("forks_count", 0),
                    }
                    for r in repos_data[:10]
                ],
                "languages": list(set(r.get("language", "") for r in repos_data if r.get("language"))),
            }
        except Exception as e:
            return {"error": f"Failed to fetch GitHub data: {str(e)}"}


# ─── Resume Parsing ────────────────────────────────────────────────────────
def parse_resume(file_bytes: bytes) -> str:
    """Extract text from PDF resume"""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        return f"Error parsing PDF: {str(e)}"


# ─── Profile Scoring ──────────────────────────────────────────────────────
def score_profile(linkedin: dict, resume: str, github: dict) -> dict:
    """Score the LinkedIn profile across 6 dimensions"""
    scores = {
        "headline": 0,
        "about": 0,
        "experience": 0,
        "skills": 0,
        "education": 0,
        "engagement": 0,
    }
    recommendations = []

    # Headline scoring (0-100)
    headline = linkedin.get("headline", "") if linkedin else ""
    if headline:
        scores["headline"] = 30
        if len(headline) > 50:
            scores["headline"] += 20
        if len(headline) > 100:
            scores["headline"] += 20
        if "|" in headline or "•" in headline or "—" in headline:
            scores["headline"] += 15
        if any(kw in headline.lower() for kw in ["help", "specialist", "expert", "leader", "engineer", "developer"]):
            scores["headline"] += 15
    else:
        recommendations.append("Add a compelling headline — it's the first thing people see")

    # About scoring (0-100)
    about = linkedin.get("about", "") if linkedin else ""
    if about:
        scores["about"] = 30
        if len(about) > 200:
            scores["about"] += 20
        if len(about) > 500:
            scores["about"] += 15
        if len(about) > 1000:
            scores["about"] += 10
        if any(c in about for c in ["📧", "🔗", "💡", "🚀", "→", "•"]):
            scores["about"] += 10
        if "http" in about or "@" in about:
            scores["about"] += 15
    else:
        recommendations.append("Write an About section — profiles with summaries get 10x more views")

    # Experience scoring (0-100)
    experience = linkedin.get("experience", []) if linkedin else []
    if experience:
        scores["experience"] = 30
        if len(experience) >= 2:
            scores["experience"] += 15
        if len(experience) >= 4:
            scores["experience"] += 15
        has_descriptions = sum(1 for e in experience if e.get("description"))
        if has_descriptions > 0:
            scores["experience"] += 20
        if has_descriptions == len(experience):
            scores["experience"] += 20
    else:
        recommendations.append("Add work experience with detailed bullet points")

    # Skills scoring (0-100)
    skills = linkedin.get("skills", []) if linkedin else []
    if skills:
        scores["skills"] = 40
        if len(skills) >= 5:
            scores["skills"] += 20
        if len(skills) >= 10:
            scores["skills"] += 20
        if len(skills) >= 20:
            scores["skills"] += 20
    else:
        recommendations.append("Add at least 10 relevant skills to improve search visibility")

    # Education scoring (0-100)
    education = linkedin.get("education", []) if linkedin else []
    if education:
        scores["education"] = 50
        if len(education) >= 2:
            scores["education"] += 25
        if any(e.get("field") for e in education):
            scores["education"] += 25
    else:
        scores["education"] = 30  # Not everyone has formal education listed

    # Engagement scoring (0-100) — based on GitHub + connections
    if github and not github.get("error"):
        scores["engagement"] = 40
        if github.get("followers", 0) > 10:
            scores["engagement"] += 15
        if github.get("public_repos", 0) > 5:
            scores["engagement"] += 15
        if github.get("public_repos", 0) > 15:
            scores["engagement"] += 15
        if github.get("followers", 0) > 50:
            scores["engagement"] += 15
    else:
        scores["engagement"] = 40

    connections = linkedin.get("connections", 0) if linkedin else 0
    if connections > 100:
        scores["engagement"] = min(100, scores["engagement"] + 10)
    if connections > 500:
        scores["engagement"] = min(100, scores["engagement"] + 10)

    # Calculate overall
    overall = round(sum(scores.values()) / len(scores))

    # Generate post ideas based on profile
    post_ideas = generate_post_ideas(linkedin, github, resume)

    return {
        "overall": overall,
        "sections": scores,
        "recommendations": recommendations,
        "post_ideas": post_ideas,
    }


def generate_post_ideas(linkedin: dict, github: dict, resume: str) -> list:
    """Generate content post ideas based on profile data"""
    ideas = []

    if linkedin:
        headline = linkedin.get("headline", "")
        experience = linkedin.get("experience", [])
        if experience:
            latest = experience[0]
            ideas.append(f"🎯 '3 lessons I learned as a {latest.get('title', 'professional')} at {latest.get('company', 'my company')}'")
            ideas.append(f"📊 'The biggest misconception about {latest.get('title', 'my role')}...'")

    if github and not github.get("error"):
        languages = github.get("languages", [])
        if languages:
            ideas.append(f"💻 'Why I chose {languages[0]} for my latest project (and what surprised me)'")
        repos = github.get("top_repos", [])
        if repos:
            ideas.append(f"🚀 'I built {repos[0].get('name', 'a project')} — here's what I learned about {repos[0].get('language', 'coding')}'")

    # Generic ideas
    ideas.extend([
        "📈 'The #1 thing that accelerated my career growth (it's not what you think)'",
        "🤔 'Hot take: [controversial opinion about your industry]'",
        "📚 'The book that changed how I approach [your field]'",
    ])

    return ideas[:6]


# ─── API Endpoints ─────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze_profile(
    resume: Optional[UploadFile] = File(None),
    github_url: Optional[str] = Form(None),
    linkedin_url: Optional[str] = Form(None),
    li_at_cookie: Optional[str] = Form(None),
):
    """Analyze LinkedIn profile, resume, and GitHub"""
    results = {
        "linkedin": None,
        "resume": None,
        "github": None,
    }

    # Scrape LinkedIn
    if linkedin_url and li_at_cookie:
        linkedin_data = await scrape_linkedin(linkedin_url, li_at_cookie)
        results["linkedin"] = linkedin_data
        profile_store["linkedin"] = linkedin_data
    elif linkedin_url:
        results["linkedin"] = {"error": "li_at cookie is required for LinkedIn scraping"}

    # Parse resume
    if resume:
        file_bytes = await resume.read()
        resume_text = parse_resume(file_bytes)
        results["resume"] = resume_text
        profile_store["resume"] = resume_text

    # Scrape GitHub
    if github_url:
        github_data = await scrape_github(github_url)
        results["github"] = github_data
        profile_store["github"] = github_data

    # Score the profile
    analysis = score_profile(
        results["linkedin"],
        results["resume"],
        results["github"],
    )
    results["analysis"] = analysis
    profile_store["analysis"] = analysis

    return results


class ChatRequest(BaseModel):
    messages: List[dict]
    model: Optional[str] = None
    hf_token: Optional[str] = None


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat with AI about profile optimization"""
    token = request.hf_token or get_hf_token()
    if not token:
        raise HTTPException(status_code=400, detail="No HF token available. Set HF_TOKEN env var or provide hf_token.")

    model = request.model or AI_MODEL

    # Build context from stored profile data
    context_parts = []
    if profile_store["linkedin"]:
        context_parts.append(f"## LinkedIn Profile Data:\n{json.dumps(profile_store['linkedin'], indent=2)}")
    if profile_store["resume"]:
        context_parts.append(f"## Resume Content:\n{profile_store['resume'][:3000]}")
    if profile_store["github"]:
        context_parts.append(f"## GitHub Profile:\n{json.dumps(profile_store['github'], indent=2)}")
    if profile_store["analysis"]:
        context_parts.append(f"## Profile Analysis Scores:\n{json.dumps(profile_store['analysis'], indent=2)}")

    context = "\n\n".join(context_parts)

    # Build system message with context
    system_message = SYSTEM_PROMPT
    if context:
        system_message += f"\n\n--- USER'S PROFILE DATA (use this to give personalized advice) ---\n\n{context}"

    # Build messages for API
    api_messages = [{"role": "system", "content": system_message}]
    api_messages.extend(request.messages)

    # Call HuggingFace Router
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": api_messages,
        "max_tokens": 1000,
        "temperature": 0.7,
    }

    async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
        try:
            resp = await client.post(AI_ENDPOINT, headers=headers, json=payload)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"AI API error: {resp.text}"
                )
            data = resp.json()
            return {
                "response": data["choices"][0]["message"]["content"],
                "model": model,
            }
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="AI request timed out")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI request failed: {str(e)}")


# ─── Serve Frontend ────────────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse("web/static/index.html")


app.mount("/static", StaticFiles(directory="web/static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
