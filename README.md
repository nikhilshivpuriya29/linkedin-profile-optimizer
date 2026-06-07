# 🚀 LinkedIn Profile Optimizer

**AI-powered multi-agent pipeline that analyzes your LinkedIn profile, scores every section, and generates optimized content to boost your visibility and engagement.**

Built with Python, Hugging Face models, and a human-in-the-loop approval workflow — so nothing changes on your profile without your explicit approval.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-200%2B_passing-brightgreen.svg)](#testing)

---

## 🎯 What It Does

```
Your LinkedIn Profile → AI Analysis → Score (0-100) → Optimized Content → You Approve → Published
```

1. **Extracts** your LinkedIn profile data (headline, about, experience, skills, posts)
2. **Pulls** your GitHub activity (repos, languages, contributions)
3. **Scores** every section on a 0-100 scale with specific improvement factors
4. **Generates** optimized content (headlines, about sections, post ideas, banner suggestions)
5. **Shows** you everything side-by-side before any changes happen
6. **Tracks** engagement improvements after you apply changes

---

## ⚡ Quick Start (5 minutes)

### Prerequisites

- Python 3.11 or newer
- A Hugging Face account (free) → [Sign up](https://huggingface.co/join)

### 1. Clone & Install

```bash
git clone https://github.com/nikhilshivpuriya29/linkedin-profile-optimizer.git
cd linkedin-profile-optimizer
python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 2. Set Up Your Token

Get a free HuggingFace token from https://huggingface.co/settings/tokens

```bash
# Create .env file
echo "HF_TOKEN=hf_your_token_here" > .env
```

### 3. Run It

```bash
# Using your resume (no LinkedIn OAuth needed)
python run_with_resume.py

# Or using the CLI
python -m linkedin_optimizer run
```

That's it! You'll see your profile scores and optimization suggestions in the terminal.

---

## 📖 How to Use

### Command Line Interface

```bash
# Run analysis now
python -m linkedin_optimizer run

# Schedule automatic weekly analysis
python -m linkedin_optimizer schedule weekly

# Pause/resume scheduled runs
python -m linkedin_optimizer pause
python -m linkedin_optimizer resume

# Check current status
python -m linkedin_optimizer status

# Review and approve suggestions
python -m linkedin_optimizer review

# View past runs
python -m linkedin_optimizer history

# View/update config
python -m linkedin_optimizer config
python -m linkedin_optimizer config --set schedule_interval=daily
```

### Resume Mode (No OAuth Required)

If you don't want to set up LinkedIn OAuth, just place your resume PDF in the project folder and run:

```bash
python run_with_resume.py
```

This parses your resume, pulls your GitHub data, runs the full analysis, and generates content suggestions — all without needing LinkedIn API access.

---

## 📊 What Gets Scored

| Section | Scoring Factors |
|---------|----------------|
| **Headline** | Keywords, character usage (out of 220), value proposition |
| **About** | Narrative structure, keyword density (1-3%), call-to-action, length |
| **Experience** | Metrics in bullets, action verbs, role alignment, formatting |
| **Skills** | Role alignment, endorsements, top 3 pinned skills |
| **Posts** | Engagement rate, posting frequency, topic consistency |
| **Banner/Photo** | Custom banner, photo resolution, brand alignment |

Each section gets a score from 0-100. Sections below 70 get automatic content generation.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Pipeline Orchestrator                     │
│                   (Sequential Execution)                      │
├─────────────┬──────────────┬────────────────┬───────────────┤
│   Stage 1   │   Stage 2    │    Stage 3     │    Stage 4    │
│  Extraction │   Analysis   │   Generation   │   Approval    │
├─────────────┼──────────────┼────────────────┼───────────────┤
│ LinkedIn    │ Analyzer     │ Content        │ Approval      │
│ MCP Client  │ Agent        │ Creator Agent  │ Workflow      │
│ GitHub API  │ (HF Model)   │ (HF Model)     │ CLI Interface │
└─────────────┴──────────────┴────────────────┴───────────────┘
         │                                            │
         ▼                                            ▼
   ┌──────────┐                              ┌──────────────┐
   │ DataStore│                              │ Engagement   │
   │ (JSON)   │                              │ Tracker      │
   └──────────┘                              └──────────────┘
```

**Key design decisions:**
- **Modular pipeline** — each stage is independent and testable
- **JSON file storage** — no database needed, fully portable
- **Heuristic + AI scoring** — works offline with heuristics, uses HF models when available
- **Human-in-the-loop** — nothing gets published without your explicit approval
- **Graceful degradation** — GitHub/HF unavailable? Pipeline continues with what's available

---

## 📁 Project Structure

```
linkedin-profile-optimizer/
├── src/linkedin_optimizer/
│   ├── __init__.py              # Package entry
│   ├── __main__.py              # python -m support
│   ├── cli.py                   # CLI with 8 subcommands
│   ├── config.py                # Configuration loading
│   ├── models.py                # All data models (22 dataclasses)
│   ├── orchestrator.py          # Pipeline coordination
│   ├── scheduler.py             # APScheduler cron scheduling
│   ├── agents/
│   │   ├── analyzer_agent.py    # Profile scoring & insights
│   │   └── content_creator_agent.py  # Content generation
│   ├── scrapers/
│   │   ├── linkedin_mcp_client.py    # LinkedIn MCP adapter
│   │   ├── profile_scraper.py        # Extraction with retries
│   │   └── github_extractor.py       # GitHub REST API
│   ├── integrations/
│   │   └── hf_client.py         # HuggingFace with retry/fallback
│   ├── persistence/
│   │   └── data_store.py        # JSON file storage
│   ├── approval/
│   │   ├── workflow.py          # Approve/reject/modify logic
│   │   └── cli_interface.py     # Rich terminal UI
│   └── tracking/
│       └── engagement_tracker.py # Post-change metric tracking
├── tests/
│   ├── unit/                    # Unit tests (fast, isolated)
│   ├── property/                # Hypothesis property-based tests
│   └── integration/             # Full pipeline integration tests
├── data/
│   └── config.json              # Your configuration
├── run_with_resume.py           # Quick-start resume mode
├── pyproject.toml               # Dependencies & build config
├── .env                         # Your secrets (not committed)
└── .gitignore                   # Keeps secrets safe
```

---

## ⚙️ Configuration

Edit `data/config.json`:

```json
{
  "linkedin_profile_url": "https://www.linkedin.com/in/your-username",
  "github_username": "your-github-username",
  "schedule_interval": "weekly",
  "models": {
    "analyzer_model_id": "mistralai/Mistral-7B-Instruct-v0.3",
    "content_model_id": "mistralai/Mistral-7B-Instruct-v0.3",
    "fallback_model_id": "google/gemma-2-9b-it"
  },
  "huggingface": {
    "api_token": "${HF_TOKEN}",
    "timeout_seconds": 30,
    "max_retries": 3
  },
  "data_dir": "./data",
  "approval_expiry_days": 7
}
```

---

## 🧪 Testing

```bash
# Run all tests
pytest

# Run only fast unit tests
pytest tests/unit/

# Run property-based tests (Hypothesis)
pytest tests/property/ -m property

# Run integration tests
pytest tests/integration/ -m integration

# Run with coverage
pytest --cov=linkedin_optimizer
```

**Test coverage: 200+ tests** including:
- 24 property-based correctness tests (Hypothesis)
- Unit tests for every component
- Full pipeline integration tests

---

## 🔧 Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.11+ | Async support, rich ecosystem |
| AI Models | Hugging Face Inference API | Free tier, state-of-the-art models |
| HTTP | httpx (async) | Modern, async-first HTTP client |
| Testing | pytest + Hypothesis | Property-based testing for correctness |
| CLI | argparse + Rich | Beautiful terminal output |
| Scheduling | APScheduler | Cron-based, async-compatible |
| Storage | JSON files | No database needed, portable |
| LinkedIn | MCP Protocol (stdio) | Browser-authenticated scraping |
| GitHub | REST API v3 | Public profile data |

---

## 🚧 Limitations

- **LinkedIn OAuth required for live data** — Resume mode works without it, but real-time profile extraction needs LinkedIn Developer app setup
- **Corporate networks** — Firewalls may block HuggingFace API; heuristic scoring works offline
- **Free HF tier rate limits** — Heavy usage may hit rate limits; exponential backoff handles this
- **No auto-publishing** — By design, all changes require manual approval
- **English only** — Content generation optimized for English profiles

---

## 🗺️ Roadmap

- [ ] Web UI dashboard (React/Next.js)
- [ ] Multi-language support
- [ ] A/B testing for headlines
- [ ] Competitor profile comparison
- [ ] LinkedIn post scheduler integration
- [ ] Chrome extension for in-page suggestions

---

## 📄 License

MIT License — use it however you want.

---

## 🙋 Contributing

Pull requests welcome! Please run `pytest` before submitting.

---

*Built with [Kiro](https://kiro.dev) — AI-powered development environment.*
