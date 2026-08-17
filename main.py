import asyncio
from typing import Optional, Any
import json
import os
import html as html_lib
import httpx
from datetime import datetime, timezone
from patchright.async_api import async_playwright
import random
from playwright_stealth import stealth_async
import company_validator
import proff_scraper

import scrapers
import company_scrapers
from config import DB_FILE, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PROXY_URL, SUPABASE_URL, SUPABASE_KEY, logger
import config

FALLBACK_FILE = "jobs_db_fallback.json"

# Maximum Telegram message length (with safety margin)
TELEGRAM_MAX_LEN = 4000

async def load_state() -> dict[str, Any]:
    state: dict[str, Any] = {"jobs": [], "company_hashes": {}}
    
    # Check if we have an un-synced fallback file from a previous failed run
    fallback_state: Optional[dict[str, Any]] = None
    if os.path.exists(FALLBACK_FILE):
        try:
            with open(FALLBACK_FILE, "r", encoding="utf-8") as f:
                fallback_state = json.load(f)
                logger.info("Found un-synced local emergency state backup.")
        except Exception as fe:
            logger.error(f"Error loading fallback file: {fe}")

    # Try Supabase first
    if SUPABASE_URL and SUPABASE_KEY:
        url = f"{SUPABASE_URL}/rest/v1/state?key=eq.scraper_state&select=value"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
        async with httpx.AsyncClient() as client:
            for attempt in range(1, 4):
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
                            
                            # Track state version for optimistic locking
                            state.setdefault("_version", 0)
                        
                        # Merge fallback state if existed
                        if fallback_state:
                            logger.info("Merging local fallback state into Supabase state...")
                            existing_job_ids = {j["job_id"] for j in state.get("jobs", []) if "job_id" in j}
                            existing_urls = {j["url"] for j in state.get("jobs", []) if "url" in j}
                            if "jobs" not in state:
                                state["jobs"] = []
                            jobs_list = state["jobs"]
                            if isinstance(jobs_list, list):
                                for fj in fallback_state.get("jobs", []):
                                    if fj.get("job_id") not in existing_job_ids and fj.get("url") not in existing_urls:
                                        jobs_list.append(fj)
                                        
                            if "company_hashes" not in state:
                                state["company_hashes"] = {}
                            hashes = state["company_hashes"]
                            if isinstance(hashes, dict):
                                hashes.update(fallback_state.get("company_hashes", {}))
                            
                        return state
                    else:
                        logger.warning(f"Supabase load attempt {attempt}/3 status {resp.status_code}")
                except Exception as e:
                    logger.warning(f"Supabase load attempt {attempt}/3 exception: {e}")
                
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                
            if fallback_state:
                logger.warning("Supabase load failed completely. Recovering state from local fallback file.")
                return fallback_state

            logger.error("Supabase load failed and no fallback file found. Returning empty state.")
            return state
                
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
    # Try Supabase with up to 3 retries
    if SUPABASE_URL and SUPABASE_KEY:
        url = f"{SUPABASE_URL}/rest/v1/state"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates"
        }
        async with httpx.AsyncClient() as client:
            # Check version for strict optimistic locking before UPSERT
            try:
                check_resp = await client.get(f"{SUPABASE_URL}/rest/v1/state?key=eq.scraper_state&select=value", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}, timeout=10.0)
                if check_resp.status_code == 200:
                    data = check_resp.json()
                    if data and isinstance(data, list):
                        db_state = data[0].get("value", {})
                        if isinstance(db_state, dict):
                            db_version = db_state.get("_version", 0)
                            current_version = state.get("_version", 0)
                            if db_version > current_version:
                                logger.error(f"Optimistic locking failed! DB version {db_version} > our version {current_version}. Aborting save to prevent data loss.")
                                return
            except Exception as e:
                logger.warning(f"Could not verify state version: {e}")
                
            for attempt in range(1, 4):
                try:
                    # Increment version for optimistic locking
                    state["_version"] = state.get("_version", 0) + 1
                    state["_last_saved"] = datetime.now(timezone.utc).isoformat()
                    resp = await client.post(url, headers=headers, json={"key": "scraper_state", "value": state}, timeout=10.0)
                    if resp.status_code in [200, 201, 204]:
                        logger.info("Saved state to Supabase via UPSERT.")
                        if os.path.exists(FALLBACK_FILE):
                            try:
                                os.remove(FALLBACK_FILE)
                            except OSError:
                                pass
                        return
                    else:
                        logger.warning(f"Supabase save attempt {attempt}/3 failed (status {resp.status_code}): {resp.text}")
                except Exception as e:
                    logger.warning(f"Supabase save attempt {attempt}/3 exception: {e}")
                
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
                
        # If all retries failed, save emergency local backup
        logger.error("All Supabase save attempts failed. Writing state to local emergency backup file.")
        try:
            with open(FALLBACK_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as fe:
            logger.error(f"Failed to write emergency fallback file: {fe}")
        return
                
    # Fallback to local only when Supabase is NOT configured
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    logger.info("Saved state to local file.")


def escape_html(text: str) -> str:
    """Escape text for Telegram HTML parse_mode. Only &, <, > need escaping."""
    return html_lib.escape(str(text))


async def _send_telegram_message(client: httpx.AsyncClient, text: str, parse_mode: str = "HTML") -> bool:
    """Send a single Telegram message with retry logic. Returns True on success."""
    if not text or not text.strip():
        logger.warning("Attempted to send empty Telegram message — skipped.")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }

    for attempt in range(1, 4):
        try:
            resp = await client.post(url, json=payload, timeout=15.0)
            if resp.status_code == 200:
                logger.info("Sent Telegram notification successfully.")
                return True
            elif resp.status_code == 429:
                # Rate limited — respect Retry-After header
                retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
                logger.warning(f"Telegram rate limited. Retrying in {retry_after}s (attempt {attempt}/3)")
                await asyncio.sleep(retry_after)
            elif resp.status_code == 400:
                # Bad request — likely formatting error. Try again without parse_mode
                logger.error(f"Telegram 400 error (attempt {attempt}/3): {resp.text}")
                if parse_mode and attempt == 2:
                    logger.warning("Retrying without parse_mode as plain text fallback...")
                    payload["parse_mode"] = ""
                    # Strip HTML tags for plain text fallback
                    import re as _re
                    payload["text"] = _re.sub(r'<[^>]+>', '', text)
                else:
                    await asyncio.sleep(2)
            else:
                logger.error(f"Telegram error {resp.status_code} (attempt {attempt}/3): {resp.text}")
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))
        except Exception as e:
            logger.error(f"Telegram send exception (attempt {attempt}/3): {e}")
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 1))

    logger.error(f"Failed to send Telegram message after 3 attempts. Message starts with: {text[:100]}...")
    return False


async def notify_telegram(jobs: list[dict], changed_companies: list[dict], cycle_alerts: Optional[list[str]] = None, news_digest: str = "", restructuring_companies: Optional[list[str]] = None):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.warning("Telegram configuration missing. Notification skipped.")
        return

    if not jobs and not changed_companies and not cycle_alerts and not news_digest:
        return

    messages: list[str] = []

    if cycle_alerts:
        for alert in cycle_alerts:
            if alert and alert.strip():
                messages.append(alert)

    # Build job notifications in HTML format
    current_msg = "🎯 <b>Nye IT-elevpladser fundet!</b>\n\n" if jobs else ""
    for job in jobs:
        title = escape_html(job['title'])
        company = escape_html(job['company'])
        source = escape_html(job['source'])
        url = job['url']

        # Check validation
        is_approved = await company_validator.check_accreditation(job['company'])
        accreditation_badge = "✅ Verificeret IT-virksomhed (CVR)" if is_approved else "⚠️ Ukendt CVR-status"

        is_restructuring = restructuring_companies and job['company'] in restructuring_companies
        restructuring_badge = "⚠️ <b>Компания проходит реструктуризацию/увольнения!</b>\n" if is_restructuring else ""

        match_score = job.get('match_score')
        if match_score is not None:
            city = escape_html(job.get('match_city', 'Ukendt'))
            reason = escape_html(job.get('match_reason', ''))
            job_str = (f"🎯 <b>{match_score}% Match</b> | {city}\n"
                       f"🔹 <b>{title}</b>\n"
                       f"🏢 {company} ({source})\n"
                       f"🎓 <i>{accreditation_badge}</i>\n"
                       f"{restructuring_badge}"
                       f"💡 <i>{reason}</i>\n"
                       f"🔗 <a href=\"{url}\">Ansøg her</a>\n\n")
        else:
            job_str = (f"🔹 <b>{title}</b>\n"
                       f"🏢 {company} ({source})\n"
                       f"🎓 <i>{accreditation_badge}</i>\n"
                       f"{restructuring_badge}"
                       f"🔗 <a href=\"{url}\">Ansøg her</a>\n\n")

        if len(current_msg) + len(job_str) > TELEGRAM_MAX_LEN:
            messages.append(current_msg)
            current_msg = job_str
        else:
            current_msg += job_str

    if current_msg and jobs:
        messages.append(current_msg)
        
    # Append cover letters as separate messages to avoid max length issues
    for job in jobs:
        draft = job.get("cover_letter_draft")
        if draft and len(draft) > 10:
            title = escape_html(job['title'])
            company = escape_html(job['company'])
            draft_msg = f"📝 <b>Udkast til ansøgning</b>\n🏢 {company} - {title}\n\n<code>{escape_html(draft)}</code>"
            messages.append(draft_msg)

    # Build company change notifications in HTML format
    current_msg = "⚠️ <b>Ændringer opdaget på karrieresider</b>\n\n" if changed_companies else ""
    if changed_companies:
        current_msg += "Strukturen på følgende sider er ændret. Der er måske en skjult elevplads:\n\n"
        for comp in changed_companies:
            company = escape_html(comp['company'])
            url = comp['url']
            comp_str = f"🏢 <b>{company}</b>\n🔗 <a href=\"{url}\">Tjek manuelt</a>\n\n"
            if len(current_msg) + len(comp_str) > TELEGRAM_MAX_LEN:
                messages.append(current_msg)
                current_msg = comp_str
            else:
                current_msg += comp_str

    if current_msg and changed_companies:
        messages.append(current_msg)

    # Guard: skip if nothing to send
    has_news = news_digest and len(news_digest.strip()) > 10
    if not messages and not has_news:
        return

    async with httpx.AsyncClient() as client:
        for msg in messages:
            await _send_telegram_message(client, msg, parse_mode="HTML")
            await asyncio.sleep(0.5)  # Respect Telegram rate limits

        # Send news digest (also HTML now — unified format)
        if has_news:
            await _send_telegram_message(client, news_digest, parse_mode="HTML")

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Elevplads & IT News Scraper")
    parser.add_argument('--mode', choices=['jobs', 'news', 'all'], default='all', help="Execution mode")
    args = parser.parse_args()

    mode = args.mode
    logger.info(f"Starting scrape run in mode: {mode}")

    # BUG-3 fix: define `now` at top level so it's available in ALL modes
    now = datetime.now(timezone.utc)
    now_ts = now.timestamp()  # BUG-4 fix: numeric timestamp for layoff comparisons

    state = await load_state()
    state_updated = False
    
    if mode in ['jobs', 'all']:
        old_jobs_list = state.get("jobs", [])
        old_company_hashes = state.get("company_hashes", {})
        
        old_jobs = {item["job_id"]: item for item in old_jobs_list}
        
        for jid, jdata in old_jobs.items():
            try:
                discovered = datetime.fromisoformat(jdata.get("discovered_at", now.isoformat()))
                if (now - discovered).days >= 30:
                    jdata["status"] = "expired"
                else:
                    if "status" not in jdata:
                        jdata["status"] = "active"
            except ValueError:
                jdata["status"] = "active"
        
        all_items = []

        # API Scrapers
        all_items.extend(await scrapers.scrape_thehub())
        all_items.extend(await scrapers.scrape_elevplads())

        # Browser Scrapers
        async with async_playwright() as p:
            browser_args = {
                "headless": True
            }
            if PROXY_URL:
                browser_args["proxy"] = {"server": PROXY_URL}
                logger.info("Using configured PROXY_URL for Playwright.")
                
            browser = await p.chromium.launch(**browser_args)
            USER_AGENTS = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
            ]
            try:
                context = await browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    locale="da-DK",
                    timezone_id="Europe/Copenhagen",
                    viewport={'width': 1920, 'height': 1080}
                )
                # Helper to run standard scrapers
                async def run_scraper(scraper_func, context):
                    page = await context.new_page()
                    await stealth_async(page)
                    try:
                        return await scraper_func(page)
                    finally:
                        await page.close()

                # Dynamic discovery on Proff (run once a week, or on empty state)
                last_proff_scrape = state.get("last_proff_scrape")
                now_dt = datetime.now(timezone.utc)
                if not last_proff_scrape or (now_dt - datetime.fromisoformat(last_proff_scrape)).days >= 7:
                    logger.info("Running weekly dynamic company discovery via Proff.dk...")
                    dynamic_companies = await proff_scraper.discover_it_companies(context)
                    if dynamic_companies:
                        existing_dynamic = state.get("dynamic_companies", [])
                        existing_names = {c["name"].lower() for c in existing_dynamic}
                        for dc in dynamic_companies:
                            if dc["name"].lower() not in existing_names:
                                existing_dynamic.append(dc)
                        state["dynamic_companies"] = existing_dynamic
                        state["last_proff_scrape"] = now_dt.isoformat()
                        await save_state(state)
                
                dynamic_companies = state.get("dynamic_companies", [])

                # Run all scrapers in parallel
                tasks = [
                    run_scraper(scrapers.scrape_laerepladsen, context),
                    run_scraper(scrapers.scrape_jobnet, context),
                    run_scraper(scrapers.scrape_jobindex, context),
                    run_scraper(scrapers.scrape_itjobbank, context),
                    company_scrapers.scrape_custom_companies(context, dynamic_companies)
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        logger.error(f"Scraper failed with exception: {res}")
                    elif isinstance(res, list):
                        all_items.extend(res)
            finally:
                await browser.close()

        # Separate scraper errors from valid items (Jobs vs Hashes)
        scraper_errors = [item for item in all_items if item.get("type") == "scraper_error"]
        valid_items = [item for item in all_items if item.get("type") != "scraper_error"]
        
        # Track Scraper Health
        KNOWN_JOB_SOURCES = ["TheHub", "Elevplads", "Laerepladsen", "Jobnet", "Jobindex", "IT-Jobbank"]
        scraper_failures = state.get("scraper_failures", {})
        notified_scraper_failures = state.get("notified_scraper_failures", {})
        errors_by_source = {err["source"]: err.get("error", "Unknown error") for err in scraper_errors}

        for src in KNOWN_JOB_SOURCES:
            if src in errors_by_source:
                scraper_failures[src] = scraper_failures.get(src, 0) + 1
                if scraper_failures[src] >= 3 and not notified_scraper_failures.get(src):
                    err_text = errors_by_source[src]
                    alert_msg = f"⚠️ <b>Сбой источника вакансий</b>\nСкрейпер <code>{escape_html(src)}</code> падает уже 3 запуска подряд:\n<code>{escape_html(err_text)}</code>"
                    await notify_telegram([], [], [], alert_msg, [])
                    notified_scraper_failures[src] = True
                    state_updated = True
            else:
                if scraper_failures.get(src, 0) > 0 and notified_scraper_failures.get(src):
                    alert_msg = f"✅ <b>Источник вакансий восстановился</b>\nСкрейпер <code>{escape_html(src)}</code> снова успешно собирает данные."
                    await notify_telegram([], [], [], alert_msg, [])
                    notified_scraper_failures[src] = False
                    state_updated = True
                scraper_failures[src] = 0

        state["scraper_failures"] = scraper_failures
        state["notified_scraper_failures"] = notified_scraper_failures

        existing_ids = {jid for jid, j in old_jobs.items()}
        new_jobs = []
        changed_companies = []
        new_company_hashes = old_company_hashes.copy()
        
        # Track seen (company, title) pairs to deduplicate across sources
        seen_titles = set()
        for jdata in old_jobs.values():
            key = (jdata.get("company", "").lower().strip(), jdata.get("title", "").lower().strip())
            seen_titles.add(key)
        
        for item in valid_items:
            if item.get("type") == "hash":
                c_name = item["company"]
                c_hash = item["hash"]
                old_hash = old_company_hashes.get(c_name)
                # If hash changed (and we had a valid MD5 old hash to compare to)
                # Avoid false alerts if old_hash was a process-randomized integer hash
                if old_hash and str(old_hash) != str(c_hash) and not str(old_hash).lstrip('-').isdigit():
                    if not item.get("llm_verified", False):
                        changed_companies.append(item)
                    else:
                        logger.info(f"Structure changed for {c_name}, but LLM verified 0 jobs. Updating hash silently.")
                    
                new_company_hashes[c_name] = str(c_hash)
            else:
                dedup_key = (item.get("company", "").lower().strip(), item.get("title", "").lower().strip())
                if item["job_id"] not in existing_ids and dedup_key not in seen_titles:
                    item["discovered_at"] = datetime.now(timezone.utc).isoformat()
                    new_jobs.append(item)
                    existing_ids.add(item["job_id"])
                    seen_titles.add(dedup_key)

        logger.info(f"Discovered {len(new_jobs)} new jobs. {len(changed_companies)} companies changed structure.")
        
        if new_jobs:
            import ai_scorer
            await ai_scorer.enrich_jobs_with_ai(new_jobs)
            
        import cycle_predictor
        cycle_alerts = cycle_predictor.analyze_and_predict(state)
        
        active_restructuring = state.get("restructuring_companies", [])
        
        # Check if we should send a reassuring daily morning heartbeat when 0 new jobs found
        today_str = now.strftime("%Y-%m-%d")
        last_heartbeat = state.get("last_heartbeat_date")
        if not new_jobs and not changed_companies and not cycle_alerts and now.hour < 12 and last_heartbeat != today_str:
            active_count = len([j for j in old_jobs.values() if j.get("status") == "active"])
            heartbeat_msg = (
                f"🔍 <b>Elevplads Monitor Status</b>\n"
                f"Проверено 5 бирж (Lærepladsen, Jobnet, Jobindex, IT-Jobbank, TheHub) и 47 карьерных страниц.\n"
                f"Новых elevplads за утро не найдено. Активных позиций в базе: {active_count}."
            )
            await notify_telegram([], [], [], heartbeat_msg, [])
            state["last_heartbeat_date"] = today_str
            state_updated = True
        else:
            await notify_telegram(new_jobs, changed_companies, cycle_alerts, "", active_restructuring)
        
        # Always save state to update expiration statuses even if no new jobs
        for nj in new_jobs:
            nj["status"] = "active"
            old_jobs[nj["job_id"]] = nj
        state["jobs"] = list(old_jobs.values())
        state_updated = True
            
        if new_company_hashes != old_company_hashes:
            state["company_hashes"] = new_company_hashes
            state_updated = True

    if mode in ['news', 'all']:
        import news_monitor
        force_post_env = os.getenv("FORCE_POST", "false").lower() == "true"
        news_result = await news_monitor.process_news(state, force_post=force_post_env)
        digests_ru = news_result.get("digests_ru", [])
        restructuring_companies = news_result.get("restructuring_companies", [])
        if "seen_news" in news_result:
            state_updated = True
            state["seen_news"] = news_result["seen_news"]
            
        if restructuring_companies:
            state["restructuring_companies"] = list(set(state.get("restructuring_companies", []) + restructuring_companies))
            
        posted_news_titles = news_result.get("posted_news_titles", [])
        
        if posted_news_titles:
            state_updated = True
            state["posted_news"] = state.get("posted_news", []) + posted_news_titles
            state["posted_news"] = state["posted_news"][-30:] # prevent infinite growth

        # 1. Feed Health-Check Alerts
        feed_failures = state.get("feed_failures", {})
        notified_feed_failures = state.get("notified_feed_failures", {})
        for source, count in feed_failures.items():
            if count >= 3 and not notified_feed_failures.get(source):
                alert_msg = f"⚠️ <b>Сбой RSS фида</b>\nИсточник <code>{escape_html(source)}</code> не отвечает уже 3 запуска подряд."
                await notify_telegram([], [], [], alert_msg, [])
                notified_feed_failures[source] = True
                state_updated = True
            elif count == 0 and notified_feed_failures.get(source):
                alert_msg = f"✅ <b>RSS фид восстановился</b>\nИсточник <code>{escape_html(source)}</code> снова работает."
                await notify_telegram([], [], [], alert_msg, [])
                notified_feed_failures[source] = False
                state_updated = True
        if "notified_feed_failures" not in state or state["notified_feed_failures"] != notified_feed_failures:
            state["notified_feed_failures"] = notified_feed_failures
            state_updated = True

        # 2. Layoffs Alerts Routing (out-of-queue)
        recent_layoff_alerts = state.get("recent_layoff_alerts", {})
        for comp in restructuring_companies:
            last_alerted = recent_layoff_alerts.get(comp, 0)
            if now_ts - last_alerted > 7 * 24 * 3600:  # 7 days deduplication (both are numeric timestamps)
                comp_escaped = escape_html(comp)
                alert_msg = f"🚨 <b>ВНИМАНИЕ: СОКРАЩЕНИЯ</b>\nЗамечены новости о сокращениях/реструктуризации в компании <b>{comp_escaped}</b>!"
                await notify_telegram([], [], [], alert_msg, [])
                recent_layoff_alerts[comp] = now_ts
                state_updated = True
        if "recent_layoff_alerts" not in state or state["recent_layoff_alerts"] != recent_layoff_alerts:
            state["recent_layoff_alerts"] = recent_layoff_alerts
            state_updated = True

        active_restructuring = state.get("restructuring_companies", [])
        for digest in digests_ru:
            if digest:
                await notify_telegram([], [], [], digest, active_restructuring)
            
    if state_updated:
        await save_state(state)

if __name__ == "__main__":
    asyncio.run(main())
