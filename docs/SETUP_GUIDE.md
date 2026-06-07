# 📋 Setup Guide

## For Everyone (No Technical Skills Needed)

---

## Step 1: Install Python

**Mac:** Open Terminal and run:
```bash
brew install python
```

**Windows:** Download from https://python.org → Install → ✅ Check "Add to PATH"

**Verify:**
```bash
python --version
# Should show 3.11 or higher
```

---

## Step 2: Download the Project

```bash
git clone https://github.com/nikhilshivpuriya29/linkedin-profile-optimizer.git
cd linkedin-profile-optimizer
```

Or download ZIP from GitHub → Unzip → Open Terminal in that folder.

---

## Step 3: Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install fastapi uvicorn python-multipart httpx PyPDF2 python-dotenv openai anthropic google-genai
```

---

## Step 4: Get Your Free AI Token

1. Go to https://huggingface.co/join (free account)
2. Go to https://huggingface.co/settings/tokens
3. Create a token → Copy it

```bash
echo "HF_TOKEN=hf_your_token_here" > .env
```

---

## Step 5: Run

```bash
python api.py
```

Open **http://localhost:8000** in your browser. Done!

---

## How to Use

### Option A: Upload Resume (Easiest)
1. Drag your resume PDF into the "Resume" box
2. Click "🔍 Analyze My Profile"
3. See your scores and chat with LinkBot

### Option B: Connect LinkedIn (Best Results)
1. Go to linkedin.com in your browser (logged in)
2. Press F12 → Application → Cookies → find `li_at` → copy value
3. Paste LinkedIn URL + cookie in the app
4. Click Analyze

### Option C: Add GitHub (Technical Profiles)
1. Enter your GitHub URL or username
2. The app pulls your repos, languages, and activity
3. LinkBot uses this for technical content suggestions

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Page won't load | Make sure `python api.py` is running |
| Chat not responding | Check you're on WiFi (not corporate VPN) |
| "No HF token" error | Create `.env` file with your token |
| LinkedIn cookie expired | Get a fresh `li_at` from browser |
| GitHub not loading | Check username is correct and public |

---

## Using from Any IDE

| IDE | Open Terminal |
|-----|-------------|
| VS Code | Ctrl+` |
| PyCharm | Alt+F12 |
| IntelliJ | Alt+F12 |
| Terminal app | Just open it |

Commands are the same everywhere:
```bash
cd path/to/linkedin-profile-optimizer
python api.py
```

---

## Updating

```bash
git pull
pip install -e ".[dev]"
python api.py
```

---

<p align="center">
  Created by <a href="https://www.linkedin.com/in/nikhilshivpuriya/">Nikhil Shivpuriya</a>
</p>
