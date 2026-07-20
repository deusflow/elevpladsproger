# 🎯 Elevpladsproger (Denmark IT Apprenticeship Scraper)

A highly advanced, AI-powered web scraper and automation tool designed to monitor IT apprenticeship (elevplads) openings in Denmark. It leverages **Groq API (Llama 3.3 70B)** and a **Stealth Anti-Detect Framework** to provide real-time, highly accurate, and bot-resistant job monitoring directly to your Telegram.

---

## ✨ Key Features

### 🧠 AI-Powered Analysis (Groq Llama 3)
- **AI Match Score**: Automatically evaluates new job postings based on target keywords (e.g., Datatekniker, IT-Elev). Sends a 0-100% match score, city, and a short Danish summary directly to Telegram.
- **Hidden Elevplads Detector**: Uses LLM to read corporate career pages. It detects "hidden" or unsolicited apprenticeship announcements (e.g., "Send an email if you want to be an IT-apprentice") that aren't listed on standard job boards.

### 🥷 Advanced Stealth & Anti-Detect Framework
- Built on `patchright` (a stealth-focused Playwright fork) and `playwright-stealth`.
- Fully spoofs `navigator.webdriver`, Canvas/WebGL fingerprints, hardware concurrency, and device memory.
- Dynamically rotates modern `User-Agent` headers and uses native Danish locales (`da-DK`) and timezones (`Europe/Copenhagen`) to completely bypass Cloudflare, DataDome, and Imperva.
- Smart HTTPX connection pooling with `PROXY_URL` support for API endpoints.

### 📅 Hiring Cycle Predictor
- Accumulates historical hiring data using a persistent state.
- Warns you 30 days in advance of historical hiring waves for major Danish companies (e.g., Arla, Netcompany, Grundfos, Vestas).

### 🚀 Massive Source Coverage
- **Standard Job Boards**: `Lærepladsen.dk`, `Jobnet.dk`, `Jobindex.dk`, `Elevplads.dk`, `IT-Jobbank.dk`, `TheHub.io`.
- **Custom Corporate Sites**: Crawls any URL added to `target_companies.json` and uses structural hashing + LLM fallback to detect changes.

---

## 🛠 Setup & Deployment

### 1. Configure Target Companies
Add URLs to monitor in `target_companies.json`:
```json
[
  {
    "name": "Vestas",
    "url": "https://www.vestas.com/en/careers/job-openings"
  },
  {
    "name": "Netcompany",
    "url": "https://www.netcompany.com/da/Career"
  }
]
```

### 2. Environment Variables
You need the following secrets configured (in your `.env` file or GitHub Secrets):
- `TELEGRAM_BOT_TOKEN`: Your Telegram Bot token.
- `TELEGRAM_CHAT_ID`: Your personal Chat ID to receive alerts.
- `GROQ_API_KEY`: API Key for Llama 3 analysis.
- `SUPABASE_URL` & `SUPABASE_KEY`: For persistent, cross-run state storage.
- `PROXY_URL`: (Optional) Residential proxy for unblocking hard WAFs.

### 3. Run Locally
```bash
pip install -r requirements.txt
patchright install chromium
python main.py
```

### 🤖 CI/CD Integration
Includes a GitHub Actions workflow (`scraper.yml`) that runs on a cron schedule. Features `actions/cache` for `ms-playwright` and automatic uploading of screenshots (`screenshots/`) if `Jobindex` or `IT-Jobbank` unexpectedly return 0 results (Cloudflare detection).
