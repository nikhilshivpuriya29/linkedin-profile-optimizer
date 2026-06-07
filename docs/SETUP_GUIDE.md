# 📋 Complete Setup Guide

## For Non-Technical Users

You don't need to be a programmer to use this tool. Follow these steps exactly.

---

## Step 1: Install Python

**Mac:**
```bash
brew install python
```

**Windows:**
Download from https://www.python.org/downloads/ → Run installer → ✅ Check "Add Python to PATH"

**Verify it works:**
```bash
python --version
# Should show: Python 3.11.x or higher
```

---

## Step 2: Download This Project

**Option A — Using Git:**
```bash
git clone https://github.com/nikhilshivpuriya29/linkedin-profile-optimizer.git
cd linkedin-profile-optimizer
```

**Option B — Download ZIP:**
1. Go to the GitHub repo page
2. Click green "Code" button → "Download ZIP"
3. Unzip the folder
4. Open Terminal/Command Prompt and `cd` into the folder

---

## Step 3: Set Up Python Environment

```bash
# Create a virtual environment (keeps things clean)
python -m venv .venv

# Activate it
# Mac/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

You should see packages installing. Wait until it finishes.

---

## Step 4: Get Your HuggingFace Token (Free)

1. Go to https://huggingface.co/join → Create free account
2. Go to https://huggingface.co/settings/tokens
3. Click "New token" → Name it "linkedin-optimizer" → Select "Read" → Create
4. Copy the token (starts with `hf_`)

---

## Step 5: Configure

Create a file called `.env` in the project folder:

```bash
# Mac/Linux:
echo "HF_TOKEN=paste_your_token_here" > .env

# Windows (PowerShell):
"HF_TOKEN=paste_your_token_here" | Out-File .env
```

Edit `data/config.json` and replace with your info:
```json
{
  "linkedin_profile_url": "https://www.linkedin.com/in/YOUR-USERNAME",
  "github_username": "YOUR-GITHUB-USERNAME"
}
```

---

## Step 6: Run!

```bash
python run_with_resume.py
```

Or if you have LinkedIn OAuth set up:
```bash
python -m linkedin_optimizer run
```

---

## What You'll See

```
LinkedIn Profile Optimizer — Resume Mode

Stage 1: Loading profile from resume PDF...
  ✓ Profile loaded

Stage 2: Extracting GitHub data...
  ✓ GitHub: 19 repos, 0 notable

Stage 3: Analyzing profile sections...
  ✓ Overall score: 55/100

┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┓
┃ Section      ┃ Score ┃ Status     ┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━┩
│ headline     │  47   │ Low        │
│ about        │  46   │ Low        │
│ experience   │  62   │ Needs Work │
└──────────────┴───────┴────────────┘

Stage 4: Generating optimized content...
  ✓ Suggested Headline: ...
  ✓ Suggested About: ...
  ✓ Post Ideas: ...

✓ Pipeline complete!
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "command not found: python" | Install Python (Step 1) |
| "No module named linkedin_optimizer" | Run `pip install -e ".[dev]"` |
| SSL certificate errors | Your network blocks HTTPS — try from home or use a VPN |
| HuggingFace API timeout | Free tier can be slow — wait 30s, it auto-retries |
| "Configuration file not found" | Make sure you're in the project folder |

---

## Using on Different IDEs

This tool works from **any terminal** regardless of your IDE:

| IDE | How to Open Terminal |
|-----|---------------------|
| **VS Code** | `Ctrl+`` ` (backtick) or View → Terminal |
| **Kiro** | Terminal panel at bottom |
| **IntelliJ/WebStorm** | Alt+F12 or View → Tool Windows → Terminal |
| **PyCharm** | Alt+F12 |
| **Sublime Text** | Install "Terminus" package |
| **Vim/Neovim** | `:terminal` |
| **No IDE** | Just use Terminal (Mac) or Command Prompt (Windows) |

The commands are the same everywhere. Just navigate to the project folder and run.
