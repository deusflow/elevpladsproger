import asyncio
import json
import os
import httpx
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async

import config
from config import logger
import scrapers

def load_db() -> set:
    if os.path.exists(config.DB_FILE):
        try:
            with open(config.DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(item["job_id"] for item in data)
        except Exception as e:
            logger.error(f"Error loading DB: {e}")
    return set()

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
    if not jobs:
        return
        
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram configuration missing. Notification skipped.")
        return

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
    existing_ids = load_db()
    all_jobs = []

    # Initialize Playwright once for all scrapers
    logger.info("Launching Playwright...")
    async with async_playwright() as p:
        browser_args = {}
        if config.PROXY_URL:
            browser_args["proxy"] = {"server": config.PROXY_URL}
            
        browser = await p.chromium.launch(headless=True, **browser_args)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)
        
        # 1. Run Lærepladsen
        lp_jobs = await scrapers.scrape_laerepladsen(page)
        all_jobs.extend(lp_jobs)
        await asyncio.sleep(2.0)
        
        # 2. Run Jobnet
        jobnet_jobs = await scrapers.scrape_jobnet(page)
        all_jobs.extend(jobnet_jobs)
        await asyncio.sleep(2.0)
        
        # 3. Run Jobindex
        jobindex_jobs = await scrapers.scrape_jobindex(page)
        all_jobs.extend(jobindex_jobs)
        await asyncio.sleep(2.0)
        
        # 4. Run LinkedIn
        linkedin_jobs = await scrapers.scrape_linkedin(page)
        all_jobs.extend(linkedin_jobs)
        
        await browser.close()

    # Deduplicate
    new_jobs = []
    for job in all_jobs:
        if job["job_id"] not in existing_ids:
            new_jobs.append(job)
            existing_ids.add(job["job_id"])

    logger.info(f"Discovered {len(new_jobs)} new jobs out of {len(all_jobs)} total scanned.")
    
    if new_jobs:
        await notify_telegram(new_jobs)
        save_db(new_jobs)

if __name__ == "__main__":
    asyncio.run(main())
