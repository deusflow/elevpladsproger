import json
import logging
import asyncio
import os
from patchright.async_api import BrowserContext, Page
import config
import hashlib
from scrapers import format_job, is_valid_job
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger("elevplads_scraper")

async def extract_links_from_frame(frame, url, found_jobs):
    try:
        links = await frame.locator("a").all()
        for link in links:
            try:
                text = (await link.inner_text()).lower()
                href = await link.get_attribute("href")
                if not href: continue
                
                if "datatekniker" in text or "it-elev" in text or "elevplads" in text:
                    if href.startswith("http"):
                        job_url = href
                    else:
                        job_url = url.rstrip("/") + "/" + href.lstrip("/")
                        
                    found_jobs.append({
                        "title": f"Mulig stilling: {(await link.inner_text()).strip()}",
                        "url": job_url
                    })
            except Exception:
                pass
    except Exception:
        pass
        
    for child in frame.child_frames:
        await extract_links_from_frame(child, url, found_jobs)

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
async def _do_scrape_company(page: Page, url: str):
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000) # Give extra time for JS/Iframes to render
    
    found_jobs = []
    await extract_links_from_frame(page.main_frame, url, found_jobs)
            
    # Structural hash: try to target the content area first, fall back to body
    content_el = page.locator("main, article, [class*='job'], [class*='career'], [class*='stilling'], [id*='job'], [id*='career']")
    if await content_el.count() > 0:
        body_text = await content_el.first.inner_text()
    else:
        body_text = await page.inner_text("body")
    
    import re
    clean_text = re.sub(r'\s+', '', body_text)
    rounded_len = len(clean_text) // 200 * 200
    structural_hash = hashlib.md5(f"{rounded_len}".encode()).hexdigest()
    
    return found_jobs, body_text, structural_hash


async def scrape_company(context: BrowserContext, company: dict, sem: asyncio.Semaphore) -> list[dict]:
    name = company.get("name")
    url = company.get("url")
    if not name or not url:
        return []
        
    async with sem:
        logger.info(f"Crawling {name}: {url}")
        page = await context.new_page()
        jobs = []
        try:
            found_jobs, body_text, structural_hash = await _do_scrape_company(page, url)
            
            if found_jobs:
                for fj in found_jobs:
                    fj_title = fj["title"].replace("Mulig stilling: ", "")
                    # Validate through the same filter as other scrapers
                    if is_valid_job(fj_title, "", name, ""):
                        job_id = hashlib.md5(f"{name}_{fj_title}_{fj['url']}".encode()).hexdigest()
                        jobs.append(format_job(
                            job_id=job_id,
                            title=fj["title"],
                            company=name,
                            url=fj["url"],
                            source="UniversalCrawler"
                        ))
            elif "datatekniker" in body_text.lower():
                jobs.append(format_job(
                    job_id=f"custom_{name.replace(' ', '_').lower()}",
                    title="Mulig IT-stilling fundet i teksten på siden!",
                    company=name,
                    url=url,
                    source="UniversalCrawler"
                ))
            else:
                # Return hash object for state diffing
                jobs.append({
                    "type": "hash",
                    "company": name,
                    "url": url,
                    "hash": str(structural_hash)
                })
        except Exception as e:
            logger.error(f"Failed to crawl {name} ({url}): {e}")
            try:
                os.makedirs("screenshots", exist_ok=True)
                safe_name = name.replace(' ', '_').lower()
                screenshot_path = f"screenshots/{safe_name}_error.png"
                await page.screenshot(path=screenshot_path)
                logger.info(f"Saved error screenshot for {name} to {screenshot_path}")
            except Exception as se:
                logger.error(f"Failed to capture screenshot for {name}: {se}")
        finally:
            await page.close()
            
        return jobs

async def scrape_custom_companies(context: BrowserContext) -> list[dict]:
    jobs = []
    try:
        with open("target_companies.json", "r", encoding="utf-8") as f:
            companies = json.load(f)
    except Exception as e:
        logger.error(f"Could not load target_companies.json: {e}")
        return jobs

    logger.info(f"Crawling {len(companies)} custom companies in parallel...")
    
    sem = asyncio.Semaphore(3)
    tasks = [scrape_company(context, company, sem) for company in companies]
    results = await asyncio.gather(*tasks)
    
    for sublist in results:
        jobs.extend(sublist)
        
    return jobs

