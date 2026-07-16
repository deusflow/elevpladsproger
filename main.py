import asyncio
import json
import os
import httpx
from datetime import datetime
from patchright.async_api import async_playwright

import scrapers
import company_scrapers
from config import DB_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROXY_URL, logger
import config

def load_db() -> set:
    if os.path.exists(config.DB_FILE):
        try:
            with open(config.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(item["job_id"] for item in data)
        except Exception as e:
            logger.error(f"Error loading DB: {e}")
    return set()

def load_jobs() -> dict:
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {item["job_id"]: item for item in data}
        except Exception as e:
            logger.error(f"Error loading DB: {e}")
    return {}

def save_db(new_jobs: list[dict]):
    existing_data = []
    if os.path.exists(config.DB_FILE):
        try:
            with open(config.DB_FILE, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            pass
            
    existing_data.extend(new_jobs)
    with open(config.DB_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, indent=2, ensure_ascii=False)
    logger.info(f"Saved {len(new_jobs)} new jobs to database.")

def escape_markdown_v2(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

async def notify_telegram(jobs: list[dict]):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram configuration missing. Notification skipped.")
        return

    if not jobs:
        message = "*No new IT Elevpladser found\\.*"
    else:
        message = "*Nye IT Elevpladser (Midtjylland)*\n\n"
        for job in jobs:
            title = escape_markdown_v2(job['title'])
            company = escape_markdown_v2(job['company'])
            source = escape_markdown_v2(job['source'])
            url = escape_markdown_v2(job['url'])
            
            message += f"🔹 *{title}*\n"
            message += f"🏢 {company} ({source})\n"
            message += f"🔗 [Ansøg her]({url})\n\n"

    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True
    }
    
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=10.0)
            if resp.status_code != 200:
                logger.error(f"Failed to send telegram notification: {resp.text}")
            else:
                logger.info("Sent Telegram notification successfully.")
        except Exception as e:
            logger.error(f"Error sending to telegram: {e}")

async def main():
    logger.info("Starting scrape run...")
    
    # Load and clean old jobs (Retention logic: older than 30 days)
    old_jobs = load_jobs()
    now = datetime.now()
    retained_jobs = {}
    for jid, jdata in old_jobs.items():
        try:
            discovered = datetime.fromisoformat(jdata.get("discovered_at", now.isoformat()))
            if (now - discovered).days < 30:
                retained_jobs[jid] = jdata
        except ValueError:
            retained_jobs[jid] = jdata
            
    if len(retained_jobs) < len(old_jobs):
        logger.info(f"Cleaned up {len(old_jobs) - len(retained_jobs)} old jobs from DB.")
    old_jobs = retained_jobs
    
    all_jobs = []

    # HTTPX Scrapers (No browser)
    all_jobs.extend(await scrapers.scrape_laerepladsen())
    all_jobs.extend(await scrapers.scrape_elevplads())
    all_jobs.extend(await scrapers.scrape_thehub())

    # Playwright Scrapers
    async with async_playwright() as p:
        browser_args = {
            "headless": True
        }
        if PROXY_URL:
            browser_args["proxy"] = {"server": PROXY_URL}
            logger.info("Using configured PROXY_URL for Playwright.")
            
        browser = await p.chromium.launch(**browser_args)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Run standard scrapers
        all_jobs.extend(await scrapers.scrape_jobnet(page))
        all_jobs.extend(await scrapers.scrape_jobindex(page))
        all_jobs.extend(await scrapers.scrape_itjobbank(page))
        
        # Custom Corporate Scrapers
        all_jobs.extend(await company_scrapers.scrape_custom_companies(page))

        await browser.close()

    # Deduplicate
    existing_ids = set(old_jobs.keys())
    new_jobs = []
    for job in all_jobs:
        if job["job_id"] not in existing_ids:
            job["discovered_at"] = datetime.now().isoformat()
            new_jobs.append(job)
            existing_ids.add(job["job_id"])

    logger.info(f"Discovered {len(new_jobs)} new jobs out of {len(all_jobs)} total scanned.")
    
    await notify_telegram(new_jobs)
    if new_jobs:
        save_db(new_jobs)

if __name__ == "__main__":
    asyncio.run(main())
