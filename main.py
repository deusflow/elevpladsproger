import asyncio
import json
import os
import httpx
from datetime import datetime
from patchright.async_api import async_playwright

import scrapers
import company_scrapers
from config import DB_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROXY_URL, SUPABASE_URL, SUPABASE_KEY, logger
import config

async def load_state() -> dict:
    state = {"jobs": [], "company_hashes": {}}
    
    # Try Supabase first
    if SUPABASE_URL and SUPABASE_KEY:
        url = f"{SUPABASE_URL}/rest/v1/state?key=eq.scraper_state&select=value"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, headers=headers, timeout=10.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data and isinstance(data, list):
                        loaded = data[0].get("value", {})
                        if isinstance(loaded, dict) and "jobs" in loaded:
                            state = loaded
                        elif isinstance(loaded, list):
                            state["jobs"] = loaded
                    return state
                else:
                    logger.error(f"Supabase returned status {resp.status_code}. Aborting to prevent local data overwrite.")
                    import sys
                    sys.exit(1)
            except Exception as e:
                logger.error(f"Failed to connect to Supabase: {e}. Aborting execution.")
                import sys
                sys.exit(1)
                
    # Fallback to local DB_FILE only if Supabase is not configured
    elif os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict) and "jobs" in loaded:
                    state = loaded
                elif isinstance(loaded, list):
                    state["jobs"] = loaded
        except Exception as e:
            logger.error(f"Error loading local state: {e}")
            
    return state

async def save_state(state: dict):
    # Try Supabase first
    if SUPABASE_URL and SUPABASE_KEY:
        url = f"{SUPABASE_URL}/rest/v1/state"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, headers=headers, json={"key": "scraper_state", "value": state}, timeout=10.0)
                if resp.status_code in [200, 201, 204]:
                    logger.info("Saved state to Supabase via UPSERT.")
                    return
                else:
                    logger.error(f"Failed to save state to Supabase (status {resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"Error saving to Supabase: {e}")
                
        # If Supabase is configured but save failed, do NOT silently fall back
        # to a local file that will vanish after CI/CD completes
        logger.critical("State save to Supabase failed. Local fallback skipped to prevent duplicate notifications on next run.")
        return
                
    # Fallback to local only when Supabase is NOT configured
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("Saved state to local file.")


def escape_markdown_v2(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in escape_chars else c for c in text)

async def notify_telegram(jobs: list[dict], changed_companies: list[dict]):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram configuration missing. Notification skipped.")
        return

    messages = []
    
    current_msg = "*Nye IT Elevpladser (Midtjylland)*\n\n" if jobs else ""
    for job in jobs:
        title = escape_markdown_v2(job['title'])
        company = escape_markdown_v2(job['company'])
        source = escape_markdown_v2(job['source'])
        # URLs must NOT be escaped — Telegram MarkdownV2 requires raw URLs inside [text](url)
        url = job['url']
        
        job_str = f"🔹 *{title}*\n🏢 {company} \\({source}\\)\n🔗 [Ansøg her]({url})\n\n"
        
        if len(current_msg) + len(job_str) > 4000:
            messages.append(current_msg)
            current_msg = job_str
        else:
            current_msg += job_str
            
    if current_msg and jobs:
        messages.append(current_msg)
        
    current_msg = "⚠️ *Ændringer opdaget på karrieresider*\n\n" if changed_companies else ""
    if changed_companies:
        current_msg += "Strukturen på følgende sider er ændret\\. Der er måske en skjult elevplads:\n\n"
        for comp in changed_companies:
            company = escape_markdown_v2(comp['company'])
            # URLs must NOT be escaped
            url = comp['url']
            comp_str = f"🏢 *{company}*\n🔗 [Tjek manuelt]({url})\n\n"
            if len(current_msg) + len(comp_str) > 4000:
                messages.append(current_msg)
                current_msg = comp_str
            else:
                current_msg += comp_str
                
    if current_msg and changed_companies:
        messages.append(current_msg)
        
    if not messages:
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        for msg in messages:
            payload = {
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": msg,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True
            }
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
    
    state = await load_state()
    old_jobs_list = state.get("jobs", [])
    old_company_hashes = state.get("company_hashes", {})
    
    old_jobs = {item["job_id"]: item for item in old_jobs_list}
    
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
    
    all_items = []

    # API Scrapers
    all_items.extend(await scrapers.scrape_thehub())

    # Browser Scrapers
    async with async_playwright() as p:
        browser_args = {
            "headless": True
        }
        if PROXY_URL:
            browser_args["proxy"] = {"server": PROXY_URL}
            logger.info("Using configured PROXY_URL for Playwright.")
            
        browser = await p.chromium.launch(**browser_args)
        try:
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            # Helper to run standard scrapers
            async def run_scraper(scraper_func, context):
                page = await context.new_page()
                try:
                    return await scraper_func(page)
                finally:
                    await page.close()

            # Run all scrapers in parallel
            tasks = [
                run_scraper(scrapers.scrape_laerepladsen, context),
                run_scraper(scrapers.scrape_elevplads, context),
                run_scraper(scrapers.scrape_jobnet, context),
                run_scraper(scrapers.scrape_jobindex, context),
                run_scraper(scrapers.scrape_itjobbank, context),
                company_scrapers.scrape_custom_companies(context)
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"Scraper failed with exception: {res}")
                elif isinstance(res, list):
                    all_items.extend(res)
        finally:
            await browser.close()

    # Process items (Jobs vs Hashes)
    existing_ids = set(old_jobs.keys())
    new_jobs = []
    changed_companies = []
    new_company_hashes = old_company_hashes.copy()
    
    # Track seen (company, title) pairs to deduplicate across sources
    seen_titles = set()
    for jdata in old_jobs.values():
        key = (jdata.get("company", "").lower().strip(), jdata.get("title", "").lower().strip())
        seen_titles.add(key)
    
    for item in all_items:
        if item.get("type") == "hash":
            c_name = item["company"]
            c_hash = item["hash"]
            old_hash = old_company_hashes.get(c_name)
            # If hash changed (and we had a valid MD5 old hash to compare to)
            # Avoid false alerts if old_hash was a process-randomized integer hash
            if old_hash and str(old_hash) != str(c_hash) and not str(old_hash).lstrip('-').isdigit():
                changed_companies.append(item)
                
            new_company_hashes[c_name] = str(c_hash)
        else:
            dedup_key = (item.get("company", "").lower().strip(), item.get("title", "").lower().strip())
            if item["job_id"] not in existing_ids and dedup_key not in seen_titles:
                item["discovered_at"] = datetime.now().isoformat()
                new_jobs.append(item)
                existing_ids.add(item["job_id"])
                seen_titles.add(dedup_key)

    logger.info(f"Discovered {len(new_jobs)} new jobs. {len(changed_companies)} companies changed structure.")
    
    await notify_telegram(new_jobs, changed_companies)
    
    state_updated = False
    if new_jobs:
        old_jobs_list = list(old_jobs.values()) + new_jobs
        state["jobs"] = old_jobs_list
        state_updated = True
        
    if new_company_hashes != old_company_hashes:
        state["company_hashes"] = new_company_hashes
        state_updated = True
        
    if state_updated or not old_jobs_list:
        # Also save if old_jobs_list is empty to initialize DB
        await save_state(state)

if __name__ == "__main__":
    asyncio.run(main())
