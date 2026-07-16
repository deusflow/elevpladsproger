import json
import logging
from patchright.async_api import Page
import config
from scrapers import format_job

logger = logging.getLogger("elevplads_scraper")

async def scrape_custom_companies(page: Page) -> list[dict]:

    jobs = []
    try:
        with open("target_companies.json", "r", encoding="utf-8") as f:
            companies = json.load(f)
    except Exception as e:
        logger.error(f"Could not load target_companies.json: {e}")
        return jobs

    logger.info(f"Crawling {len(companies)} custom companies...")

    for company in companies:
        name = company.get("name")
        url = company.get("url")
        if not name or not url:
            continue
            
        logger.info(f"Crawling {name}: {url}")
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            
            links = await page.locator("a").all()
            found_job_link = False
            for link in links:
                try:
                    text = (await link.inner_text()).lower()
                    href = await link.get_attribute("href")
                    if not href: continue
                    
                    if "datatekniker" in text or "it-supporter" in text or "it-elev" in text or "elevplads" in text:
                        if href.startswith("http"):
                            job_url = href
                        else:
                            # Basic relative path handling
                            job_url = url.rstrip("/") + "/" + href.lstrip("/")
                            
                        job_id = job_url.split("/")[-1] or job_url
                        jobs.append(format_job(
                            job_id=job_id,
                            title=f"Mulig stilling: {(await link.inner_text()).strip()}",
                            company=name,
                            url=job_url,
                            source="UniversalCrawler"
                        ))
                        found_job_link = True
                except Exception:
                    pass
            
            if not found_job_link:
                # Fallback: check whole page body just in case it's not an a-tag but a div or span
                body_text = await page.inner_text("body")
                if "datatekniker" in body_text.lower():
                     jobs.append(format_job(
                        job_id=f"custom_{name.replace(' ', '_').lower()}",
                        title="Mulig IT-stilling fundet i teksten på siden!",
                        company=name,
                        url=url,
                        source="UniversalCrawler"
                    ))
                    
        except Exception as e:
            logger.error(f"Failed to crawl {name} ({url}): {e}")
            
    return jobs
