# 🚀 LinkedIn Profile Optimizer

**AI-powered tool that analyzes your LinkedIn profile, scores every section, and gives you copy-paste-ready improvements — all running locally on your machine.**

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![AI](https://img.shields.io/badge/AI-Llama_3.3_70B-purple.svg)](#ai-chat)

---

## What It Does

```
Your Profile Data  →  AI Analysis  →  Score (0-100)  →  Recommendations  →  Chat for Help
```

| Input | How |
|-------|-----|
| **LinkedIn Profile** | Paste URL + browser cookie (li_at) |
| **Resume PDF** | Upload / drag-drop |
| **GitHub** | Paste URL or username |

| Output | What You Get |
|--------|-------------|
| **Score** | 0-100 across 6 sections (headline, about, experience, skills, education, engagement) |
| **Recommendations** | Specific actionable fixes for each weak section |
| **AI Chat** | Ask LinkBot anything — it knows your full profile and gives copy-paste text |
| **Post Ideas** | Generated content ideas based on your background |

---

## ⚡ Quick Start

```bash
# 1. Clone
git clone https://github.com/nikhilshivpuriya29/linkedin-profile-optimizer.git
cd linkedin-profile-optimizer

# 2. Install
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install fastapi uvicorn python-multipart httpx PyPDF2 python-dotenv openai anthropic google-genai

# 3. Set your HuggingFace token (free)
echo "HF_TOKEN=your_hf_token_here" > .env

# 4. Run
python api.py
```

Open **http://localhost:8000** — that's it.

---

## 🖥️ Web UI

The app runs entirely in your browser at `localhost:8000`:

**Left panel:**
- 3 input cards: LinkedIn URL (+cookie), Resume PDF (drag-drop), GitHub URL
- Click "Analyze My Profile"
- See scores, recommendations, post ideas, profile data

**Right panel:**
- AI Chat (LinkBot) — always visible
- Quick action buttons: Headline, About, Posts, Skills, Experience, Keywords
- Powered by Llama 3.3 70B (free, via HuggingFace)

**Features:**
- Dark / Light mode toggle
- Responsive layout
- No external accounts needed (HuggingFace free tier is enough)

---

## 🤖 AI Chat (LinkBot)

LinkBot is your personal LinkedIn optimization coach. After analysis, it has full context of:
- Your LinkedIn profile data
- Your resume content
- Your GitHub repos and languages
- Your section scores

**Ask it things like:**
- "Rewrite my headline"
- "Write me a better About section"
- "Give me 5 post ideas for this week"
- "What keywords should I target?"
- "How can I improve my experience bullets?"

**AI Models supported:**
| Model | Provider | Cost |
|-------|----------|------|
| Llama 3.3 70B (default) | HuggingFace Router | Free |
| GPT-4o-mini | OpenAI | Paid |
| Claude Sonnet | Anthropic | Paid |
| Gemini 2.0 Flash | Google | Free tier |

---

## 🔗 LinkedIn Data Extraction

To pull live data from LinkedIn, you need the `li_at` cookie from your browser:

1. Go to linkedin.com (while logged in)
2. Press F12 → Application tab → Cookies → linkedin.com
3. Find `li_at` → copy the value
4. Paste it in the app's LinkedIn section

This gives authenticated access to your full profile — no developer app needed.

---

## 📄 Resume Mode

Don't want to set up LinkedIn cookies? Just upload your resume PDF:
- Extracts all sections automatically
- Works with any PDF format
- Gives the same quality analysis

---

## 🐙 GitHub Integration

Add your GitHub URL to enrich the analysis:
- Pulls your repos, languages, and activity
- Suggests technical content ideas based on your code
- Adds open-source contributions to your profile suggestions

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                   Web UI (React + Tailwind)              │
│                 http://localhost:8000                    │
├────────────────────────────────────────────────────────┤
│                   FastAPI Backend (api.py)               │
├──────────┬──────────┬──────────┬───────────────────────┤
│ LinkedIn │  Resume  │  GitHub  │  AI Chat (LinkBot)    │
│ Voyager  │  PyPDF2  │  REST    │  Llama 3.3 70B       │
│ API      │  Parser  │  API     │  via HF Router       │
├──────────┴──────────┴──────────┴───────────────────────┤
│              Profile Scoring Engine                      │
│          (Heuristic + AI-powered analysis)              │
├────────────────────────────────────────────────────────┤
│              Core Pipeline (src/linkedin_optimizer/)     │
│  Agents | Scrapers | Persistence | Approval | Tracking  │
└────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
linkedin-profile-optimizer/
├── api.py                      # FastAPI backend (main entry)
├── web/static/index.html       # Web UI (React + Tailwind)
├── run_with_resume.py          # CLI quick-start mode
├── src/linkedin_optimizer/     # Core Python pipeline
│   ├── cli.py                  # CLI interface (8 commands)
│   ├── orchestrator.py         # Pipeline coordination
│   ├── scheduler.py            # APScheduler cron jobs
│   ├── agents/                 # AI agents (analyzer, content creator)
│   ├── scrapers/               # Data extraction (LinkedIn, GitHub)
│   ├── integrations/           # HuggingFace client
│   ├── persistence/            # JSON file storage
│   ├── approval/               # Review workflow + CLI
│   └── tracking/               # Engagement metrics
├── tests/                      # 200+ tests (unit, property, integration)
├── docs/                       # Setup guide, architecture docs
├── data/config.json            # Configuration
└── .env                        # Secrets (not committed)
```

---

## 🧪 Testing

```bash
pytest                              # All 200+ tests
pytest tests/unit/ -v               # Unit tests
pytest tests/property/ -m property  # Property-based (Hypothesis)
pytest tests/integration/           # Integration tests
```

---

## ⚙️ Configuration

Edit `data/config.json` or use the CLI:

```bash
python -m linkedin_optimizer config
python -m linkedin_optimizer config --set schedule_interval=daily
```

---

## 📊 CLI Commands

```bash
python -m linkedin_optimizer run        # Run analysis
python -m linkedin_optimizer status     # Check status
python -m linkedin_optimizer review     # Approve suggestions
python -m linkedin_optimizer history    # View past runs
python -m linkedin_optimizer schedule weekly  # Auto-schedule
python -m linkedin_optimizer pause      # Pause scheduler
python -m linkedin_optimizer resume     # Resume scheduler
```

---

## 🚧 Limitations

- LinkedIn live scraping needs `li_at` cookie (expires periodically)
- Corporate networks may block HuggingFace API (use mobile hotspot)
- Free HF tier has rate limits (generous for personal use)
- English-optimized content generation
- No auto-publishing (all changes need your approval)

---

## 🗺️ Roadmap (v2)

- [ ] Separate Resume view (LaTeX-style rendering, before/after)
- [ ] Separate LinkedIn view (profile card before/after)
- [ ] Minimizable chat panel
- [ ] Better responsive mobile design
- [ ] Multi-platform support (Twitter/X, portfolio sites)
- [ ] A/B testing for headlines
- [ ] Chrome extension

---

## 📄 License

MIT — do whatever you want with it.

---

<p align="center">
  Built with ❤️ by <a href="https://www.linkedin.com/in/nikhilshivpuriya/"><b>Nikhil Shivpuriya</b></a>
</p>
