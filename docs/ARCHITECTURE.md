# 🏛️ Architecture & Technical Documentation

## How We Created This

This project was built using **Spec-Driven Development** with Kiro AI — a methodology where you start with requirements, design the architecture, then implement task-by-task with property-based testing ensuring correctness at every step.

### Development Process

```
Idea → Requirements (9 detailed user stories)
     → Technical Design (components, interfaces, data models)
     → Task Breakdown (43 tasks across 14 waves)
     → Implementation (wave-parallel execution)
     → Property-Based Testing (24 formal correctness properties)
     → Integration Testing (32 end-to-end scenarios)
```

**Time: Requirements to working system in one session.**

---

## High-Level Design

### System Overview

The LinkedIn Profile Optimizer is a **multi-agent pipeline** where specialized AI agents handle different aspects of profile optimization:

```
┌──────────────────────────────────────────────────────────────────┐
│                         USER                                      │
│                    (CLI Interface)                                │
└─────────────────────────┬────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                  PIPELINE ORCHESTRATOR                            │
│                                                                  │
│  Responsibilities:                                               │
│  • Sequential stage execution                                    │
│  • Error propagation (halt on failure)                           │
│  • Concurrency control (single execution)                        │
│  • Run metadata logging                                          │
│  • Graceful degradation                                          │
└────┬──────────┬──────────────┬────────────────┬─────────────────┘
     │          │              │                │
     ▼          ▼              ▼                ▼
┌─────────┐┌──────────┐┌──────────────┐┌──────────────┐
│EXTRACT  ││ANALYZE   ││GENERATE      ││APPROVE       │
│         ││          ││              ││              │
│LinkedIn ││Analyzer  ││Content       ││Approval      │
│MCP      ││Agent     ││Creator Agent ││Workflow      │
│GitHub   ││          ││              ││              │
│API      ││HF Model  ││HF Model      ││CLI Interface │
└─────────┘└──────────┘└──────────────┘└──────────────┘
     │          │              │                │
     └──────────┴──────────────┴────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │     DATA STORE       │
              │    (JSON Files)      │
              │                      │
              │ profiles/ reports/   │
              │ content/ approvals/  │
              │ engagement/ runs/    │
              └──────────────────────┘
```

### Data Flow

```
1. TRIGGER (user or scheduler)
       │
2. EXTRACT LinkedIn profile (MCP) + GitHub repos (REST)
       │
3. SCORE each section (0-100) with weighted factors
       │
4. GENERATE content for sections scoring < 70
       │
5. PRESENT to user for approval (side-by-side diff)
       │
6. APPLY approved changes + record engagement baseline
       │
7. TRACK engagement for 30 days post-change
```

---

## Low-Level Design

### Core Data Models (22 dataclasses)

```python
# Profile extraction
ProfileData          # All LinkedIn sections
ExtractionResult     # Success/failure with partial handling

# GitHub
GitHubRepo           # Single repository
GitHubContributions  # 12-month activity
GitHubData           # Aggregated GitHub profile
GitHubExtractionResult

# Analysis
FactorScore          # Individual scoring factor (0-100)
SectionScore         # Section with weighted factor average
Recommendation       # Actionable suggestion with priority
SectionInsight       # Strengths + weaknesses + recommendations
OptimizationReport   # Full analysis output

# Content generation
HeadlineSuggestion   # ≤220 chars, keywords, value prop
AboutSuggestion      # ≤2600 chars, hook, CTA
ExperienceSuggestion # Action verbs, metrics per role
PostIdea             # Topic + format + outline
BannerSuggestion     # Dimensions, colors, tagline
ContentPackage       # All suggestions bundled

# Approval
ApprovalItem         # Single reviewable change
ApprovalSession      # Group of items from one run

# Tracking
EngagementSnapshot   # Point-in-time metrics
EngagementComparison # Before/after for one metric
EngagementReport     # Full comparison with trend

# Pipeline
RunMetadata          # Start, end, status, summary
```

### Key Algorithms

**Section Scoring:**
```
score = weighted_average(factor_scores)
     where each factor is scored 0-100
     unavailable factors are excluded from average
     empty sections get score=0, missing=True
```

**Retry with Exponential Backoff:**
```
for attempt in [1, 2, 3]:
    try: call_api()
    except Timeout: raise immediately (no retry)
    except Error: wait(2^attempt seconds), retry
if all_failed and not_timeout: try fallback_model
```

**Engagement Tracking:**
```
percentage_change = ((current - baseline) / baseline) × 100
                    when baseline > 0, else 0.0
trend = "improving" if majority positive
        "declining" if majority negative
        "stable" otherwise
```

### Component Interfaces

| Component | Input | Output |
|-----------|-------|--------|
| ProfileScraper | LinkedIn URL | ExtractionResult |
| GitHubExtractor | GitHub username | GitHubExtractionResult |
| AnalyzerAgent | ProfileData + GitHubData | OptimizationReport |
| ContentCreatorAgent | Report + Profile | ContentPackage |
| ApprovalWorkflow | ContentPackage + Profile | ApprovalSession |
| EngagementTracker | change_id | EngagementReport |
| PipelineOrchestrator | PipelineConfig | RunMetadata |
| PipelineScheduler | ScheduleInterval | (triggers orchestrator) |

---

## Why These Technology Choices

| Choice | Alternatives Considered | Why This Won |
|--------|------------------------|--------------|
| **Python** | TypeScript, Go | Best AI/ML ecosystem, async support, rapid prototyping |
| **Hugging Face** | OpenAI, Anthropic | Free tier, open models, no vendor lock-in |
| **httpx** | aiohttp, requests | Modern async, connection pooling, timeout control |
| **JSON files** | SQLite, PostgreSQL | Zero setup, portable, human-readable, git-friendly |
| **APScheduler** | Celery, cron directly | Lightweight, async-native, in-process |
| **Hypothesis** | just pytest | Formal correctness properties, finds edge cases |
| **Rich** | Click, Textual | Beautiful terminal output with minimal code |
| **MCP Protocol** | Selenium, Puppeteer | LinkedIn auth via browser, official protocol |
| **Dataclasses** | Pydantic, attrs | Stdlib, no extra dependency, simple serialization |

---

## Correctness Properties (24 formal guarantees)

These are **mathematically verified** properties that hold for ALL valid inputs:

| # | Property | What It Guarantees |
|---|----------|-------------------|
| 1 | Profile parsing preserves all sections | No data lost during extraction |
| 2 | Serialization round-trip | JSON save/load is lossless |
| 3 | No partial data on total failure | Failed extraction = clean error |
| 4 | Retry respects attempt limits | Max 3 retries, backoff doubles |
| 5 | Partial extraction identifies failures | Exactly failed sections reported |
| 6 | Scoring produces valid averages | Always 0-100, mathematically correct |
| 7 | Empty sections get zero score | Missing = 0 + flag |
| 8 | Engagement rate formula correct | Verified arithmetic |
| 9 | Report structural completeness | ≥1 strength, weakness, recommendation |
| 10 | Recommendations ordered by priority | High → Medium → Low always |
| 11 | Every recommendation cites guideline | Never empty reference |
| 12 | Content targets correct sections | Only generated for score < 70 |
| 13 | Content respects constraints | Headline ≤220, about ≤2600, etc. |
| 14 | Notable repo identification | Exactly stars≥5 OR pinned |
| 15 | GitHub integration limit | At most 5 achievements in content |
| 16 | Graceful GitHub degradation | Pipeline works without GitHub |
| 17 | Pipeline stage ordering | Strict sequence, failure halts |
| 18 | Run queue serialization | Only 1 execution at a time |
| 19 | Approval item independence | Action on one doesn't affect others |
| 20 | Expiration after 7 days | Stale items auto-expire |
| 21 | 500-char input validation | Boundary enforced exactly |
| 22 | Engagement comparison correctness | Formula verified for all inputs |
| 23 | Section prioritization | Ranked by descending improvement |
| 24 | Model fallback logic | Timeout=no fallback, error=try fallback |

---

## Features

### ✅ Implemented

- Multi-section profile scoring (6 sections, 20+ factors)
- AI-powered content generation (headline, about, experience, posts, banner)
- GitHub integration (repos, languages, contributions)
- Human-in-the-loop approval workflow
- Side-by-side content comparison (terminal UI)
- Exponential backoff retry with model fallback
- Cron-based scheduling (daily/weekly/monthly)
- Engagement tracking with baseline comparison
- JSON file persistence (no database needed)
- Resume PDF input mode (no OAuth required)
- Full CLI with 8 subcommands
- 200+ automated tests with property-based verification

### 🚧 Limitations

- LinkedIn OAuth requires developer app verification
- Corporate firewalls may block HuggingFace API
- Content generation is English-only
- No web UI (CLI only)
- No auto-publishing to LinkedIn
- Free HF tier has rate limits
- Engagement tracking requires LinkedIn API access

---

## Cheatsheet

```bash
# ─── SETUP ───────────────────────────────────
git clone <repo>
cd linkedin-profile-optimizer
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
echo "HF_TOKEN=hf_xxx" > .env

# ─── RUN ─────────────────────────────────────
python run_with_resume.py          # Quick start (no OAuth)
python -m linkedin_optimizer run   # Full pipeline
python -m linkedin_optimizer status       # Check status
python -m linkedin_optimizer review       # Approve changes
python -m linkedin_optimizer history      # Past runs

# ─── SCHEDULE ────────────────────────────────
python -m linkedin_optimizer schedule weekly
python -m linkedin_optimizer pause
python -m linkedin_optimizer resume

# ─── CONFIG ──────────────────────────────────
python -m linkedin_optimizer config
python -m linkedin_optimizer config --set schedule_interval=daily
python -m linkedin_optimizer config --set models.analyzer_model_id=google/gemma-2-9b-it

# ─── TEST ────────────────────────────────────
pytest                          # All tests
pytest tests/unit/ -v           # Unit tests only
pytest tests/property/ -m property  # Property tests
pytest tests/integration/       # Integration tests

# ─── DATA ────────────────────────────────────
ls data/reports/                # View saved reports
ls data/content/                # View generated content
ls data/runs/                   # View run history
cat data/config.json            # View config
```
