# Denmark IT Apprenticeship Scraper 🇩🇰🤖

A minimalist, "ponytail-compliant" Python scraper built to search for **IT Apprenticeships (Elevplads / Lærling)** in Denmark (default: Region Midtjylland).

It crawls major job portals and individual company career sites, filters by strict keywords (like Datatekniker - Programmering/Cybersecurity), and sends instant alerts to a Telegram Channel.

## Features

- **6 Major Aggregators:** Scrapes `Lærepladsen.dk`, `Jobnet.dk`, `Jobindex.dk`, `Elevplads.dk`, `IT-Jobbank.dk`, and `TheHub.io`.
- **Universal Company Crawler:** Visist any custom list of career URLs configured in `target_companies.json` and alerts if matching keywords appear.
- **Anti-Bot Bypass:** Uses `Patchright` (modified Chromium) to bypass Cloudflare/WAF ASN bans.
- **Auto-Retention:** Automatically cleans up saved jobs older than 30 days to keep the database size minimal.
- **GitHub Actions Ready:** Configured to run on a cron job (twice a day) and auto-commit the state back to the repo.

## Quick Start

### 1. Configure Target Companies
Add companies you want to monitor directly to `target_companies.json`:
```json
[
  {
    "name": "Samson Agro",
    "url": "https://www.samson-agro.com/career/"
  }
]
```

### 2. Environment Variables
Set the following secrets in your GitHub repository or local `.env` file:
- `TELEGRAM_BOT_TOKEN`: Token from @BotFather
- `TELEGRAM_CHAT_ID`: ID of your channel/chat (e.g., `@my_channel` or `-100...`)
- `PROXY_URL` *(Optional)*: Proxy to route Playwright traffic if GitHub IPs get blocked.

### 3. Local Run
```bash
pip install -r requirements.txt
patchright install chromium
python main.py
```
