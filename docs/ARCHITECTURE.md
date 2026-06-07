# 🏛️ Architecture & Technical Documentation

## How This Was Built

Built using **Spec-Driven Development** with Kiro AI:

```
Requirements (9 user stories) → Design (components + interfaces) → Tasks (43 items) → Implementation → Testing (200+ tests)
```

---

## System Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                          │
│                   React 18 + Tailwind CSS (CDN)                   │
│                    http://localhost:8000                           │
├───────────────────────────────────────────────────────────────────┤
│                     FastAPI Backend (api.py)                       │
│                                                                   │
│  Endpoints:                                                       │
│  ├── GET  /              → Serve HTML                             │
│  ├── POST /api/analyze   → Run full profile analysis              │
│  └── POST /api/chat      → AI chat with profile context           │
├──────────┬───────────────┬────────────────┬───────────────────────┤
│ LinkedIn │    Resume      │    GitHub      │   AI (Llama 3.3 70B) │
│ Voyager  │    PyPDF2      │    REST API    │   HuggingFace Router │
│ API      │    Parser      │    v3          │   (free tier)        │
├──────────┴───────────────┴────────────────┴───────────────────────┤
│                   Core Pipeline Engine                             │
│              (src/linkedin_optimizer/)                             │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Analyzer │  │ Content  │  │ Approval │  │Engagement│        │
│  │  Agent   │  │ Creator  │  │ Workflow │  │ Tracker  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Profile  │  │  GitHub  │  │   HF     │  │  Data    │        │
│  │ Scraper  │  │Extractor │  │  Client  │  │  Store   │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└───────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

```
User uploads resume / enters LinkedIn URL / adds GitHub
          │
          ▼
┌─── /api/analyze ───┐
│                    │
│ 1. Parse Resume    │  → Extract text from PDF
│ 2. Scrape LinkedIn │  → Voyager API (needs li_at cookie)
│ 3. Fetch GitHub    │  → REST API (public, no auth)
│ 4. Score Profile   │  → Heuristic scoring across 6 dimensions
│ 5. Generate Ideas  │  → Post ideas based on background
│ 6. Store in Memory │  → Available for chat context
│                    │
└────────────────────┘
          │
          ▼
   Results shown in UI + Chat enabled
          │
          ▼
┌─── /api/chat ──────┐
│                    │
│ 1. Load profile    │  → LinkedIn + Resume + GitHub + Scores
│    context         │
│ 2. Build system    │  → Expert LinkedIn coach prompt
│    prompt          │
│ 3. Call AI model   │  → Llama 3.3 70B via HuggingFace
│ 4. Return response │  → Personalized, actionable advice
│                    │
└────────────────────┘
```

---

## Technology Choices

| Component | Technology | Why |
|-----------|-----------|-----|
| Backend | FastAPI | Async, fast, auto-docs, Python native |
| Frontend | React 18 + Tailwind (CDN) | No build step, instant load, single file |
| AI Model | Llama 3.3 70B Instruct Turbo | Free, high quality, via HuggingFace |
| AI Endpoint | router.huggingface.co/together | Reliable, OpenAI-compatible API |
| Resume Parser | PyPDF2 | Lightweight, pure Python |
| GitHub | REST API v3 | Public, no auth needed |
| LinkedIn | Voyager API | Internal API, works with session cookie |
| HTTP Client | httpx | Async, modern, timeout support |
| Storage | JSON files | Portable, no database needed |
| Testing | pytest + Hypothesis | Property-based correctness |
| Scheduling | APScheduler | Cron-based, async-compatible |

---

## Profile Scoring Algorithm

Each section scored 0-100:

**Headline (0-100):**
- Has content: +30
- Length > 50 chars: +20
- Length > 100 chars: +20
- Has separator (|, •, —): +15
- Has role keywords: +15

**About (0-100):**
- Has content: +30
- Length > 200 chars: +20
- Length > 500 chars: +15
- Length > 1000 chars: +10
- Has formatting/emojis: +10
- Has links/CTA: +15

**Experience (0-100):**
- Has entries: +30
- 2+ entries: +15
- 4+ entries: +15
- Has descriptions: +20
- All have descriptions: +20

**Skills (0-100):**
- Has skills: +40
- 5+ skills: +20
- 10+ skills: +20
- 20+ skills: +20

**Education (0-100):**
- Has entries: +50
- 2+ entries: +25
- Has field of study: +25

**Engagement (0-100):**
- GitHub repos > 5: +15
- GitHub repos > 15: +15
- GitHub followers > 10: +15
- GitHub followers > 50: +15
- LinkedIn connections > 100: +10
- LinkedIn connections > 500: +10
- Base: +40

---

## AI System Prompt (LinkBot Character)

```
You are "LinkBot" — a world-class LinkedIn Profile Optimization Coach 
with 10+ years of experience helping professionals maximize their 
LinkedIn presence.

Personality: Direct, actionable, encouraging but honest
Expertise: LinkedIn SEO, headlines, about sections, experience bullets,
           content strategy, profile visuals, algorithm knowledge

Rules:
- Give copy-paste-ready text
- Respect character limits (headline: 220, about: 2600)
- Reference LinkedIn data when possible
- Be concise (max 200 words unless writing full sections)
```

The system prompt includes the user's full profile data (LinkedIn + Resume + GitHub + Scores) so every response is personalized.

---

## Correctness Properties (24 Verified)

The core pipeline has 24 formally verified properties using Hypothesis:
- Data serialization round-trips
- Scoring math correctness
- Error handling guarantees
- Pipeline ordering
- Concurrency safety
- Approval independence
- Input validation boundaries

See `tests/property/` for all property-based tests.

---

## File Inventory

| File | Purpose | Lines |
|------|---------|-------|
| `api.py` | FastAPI backend + all logic | ~540 |
| `web/static/index.html` | Full UI (React + Tailwind) | ~500 |
| `src/linkedin_optimizer/` | Core pipeline (22 modules) | ~5000 |
| `tests/` | 200+ tests | ~4000 |
| `docs/` | Documentation | ~300 |

---

<p align="center">
  Created by <a href="https://www.linkedin.com/in/nikhilshivpuriya/">Nikhil Shivpuriya</a>
</p>
