# Denmark IT Apprenticeship Scraper

A Python scraper to monitor IT apprenticeship (elevplads) openings in Denmark.
It checks multiple job portals and custom company sites, alerting to Telegram when new postings match target keywords.

## Features
- Scrapes: `Lærepladsen.dk`, `Jobnet.dk`, `Jobindex.dk`, `Elevplads.dk`, `IT-Jobbank.dk`, `TheHub.io`.
- Custom sites: Crawls any URLs added to `target_companies.json`.
- Uses `patchright` (Chromium) to avoid basic WAF/Cloudflare blocks.
- Keeps track of seen jobs in `jobs_db.json` (auto-cleans >30 days old).
- GitHub Actions workflow included.

## Setup

1. **Companies**
   Add URLs to monitor in `target_companies.json`:
   ```json
   [
     {
       "name": "Thise Majeri",
       "url": "https://thise.dk/om-thise/job-hos-thise"
     }
   ]
   ```

2. **Environment Variables**
   Set the following:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `PROXY_URL` (optional)

3. **Run Locally**
   ```bash
   pip install -r requirements.txt
   patchright install chromium
   python main.py
   ```

