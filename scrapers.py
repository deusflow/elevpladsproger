import re
import json
import asyncio
from datetime import datetime, timezone
from playwright.async_api import Page
import config
from config import logger

def is_valid_job(title: str, postal_code: str, company: str = "") -> bool:
    title_lower = title.lower()
    company_lower = company.lower()
    
    # Check postal code (Midtjylland 7400-8999) if provided
    if postal_code and postal_code.isdigit():
        if not (7400 <= int(postal_code) <= 8999):
            return False
            
    # Check exclusions first
    for ex in config.EXCLUDE_KEYWORDS:
        if ex in title_lower:
            return False
            
    # Target enterprises logic
    is_target_enterprise = any(ent in company_lower for ent in config.TARGET_ENTERPRISES)

    # Check for target keywords
    has_target_skill = any(inc in title_lower for inc in config.TARGET_KEYWORDS)
    is_elev = "datatekniker" in title_lower or any(e in title_lower for e in config.ELEV_KEYWORDS)
    
    if (has_target_skill and is_elev) or (is_target_enterprise and is_elev):
        return True
            
    return False

def format_job(job_id: str, title: str, company: str, url: str, source: str) -> dict:
    return {
        "job_id": str(job_id),
        "title": title.strip(),
        "company": company.strip(),
        "url": url,
        "source": source,
        "discovered_at": datetime.now(timezone.utc).isoformat()
    }

async def scrape_laerepladsen(page: Page) -> list[dict]:
    jobs = []
    intercepted_data = None
    
    async def handle_response(response):
        nonlocal intercepted_data
        if "api/soeg-opslag" in response.url and not "kort" in response.url:
            try:
                text = await response.text()
                intercepted_data = json.loads(text)
                logger.info("Lærepladsen API Intercepted!")
            except Exception as e:
                logger.error(f"Error reading Lærepladsen response: {e}")

    try:
        logger.info("Starting Lærepladsen scrape via Playwright interception...")
        page.on("response", handle_response)
        
        # Load the direct search page which automatically triggers the API GET request
        url = "https://sr.laerepladsen.dk/soeg-opslag/0/Data-%20og%20kommunikationsuddannelsen/3607/Datatekniker/8871/midtjylland"
        await page.goto(url, wait_until="networkidle", timeout=30000)
            
        # Wait up to 8 seconds for interception to complete
        for _ in range(16):
            if intercepted_data:
                break
            await asyncio.sleep(0.5)
            
        if intercepted_data and "laeresteder" in intercepted_data:
            for company_item in intercepted_data["laeresteder"]:
                company_name = company_item.get("navn", "Ukendt")
                postal = str(company_item.get("postnummer", ""))
                
                postings = company_item.get("opslag", [])
                for item in postings:
                    title = item.get("titel", "") or item.get("beskrivelse", "") or "Datatekniker Elev"
                    
                    if is_valid_job(title, postal, company_name):
                        jobs.append(format_job(
                            job_id=item.get("id"),
                            title=title,
                            company=company_name,
                            url=f"https://laerepladsen.dk/elev/opslag/{item.get('id')}",
                            source="Laerepladsen"
                        ))
    except Exception as e:
        logger.error(f"Error in Lærepladsen scraper: {e}")
    finally:
        page.remove_listener("response", handle_response)
        
    return jobs

async def scrape_jobnet(page: Page) -> list[dict]:
    jobs = []
    intercepted_data = None
    
    async def handle_response(response):
        nonlocal intercepted_data
        if "CV/Sogning/Sogning" in response.url and response.request.method == "POST":
            try:
                text = await response.text()
                intercepted_data = json.loads(text)
            except Exception as e:
                logger.error(f"Error reading Jobnet response: {e}")

    try:
        logger.info("Starting Jobnet scrape via Playwright interception...")
        page.on("response", handle_response)
        await page.goto("https://jobnet.dk/CV/FindWork", wait_until="networkidle", timeout=30000)
        
        # Enter "datatekniker" into the search box and trigger search
        search_input = page.locator("input[type='search']:visible, input[placeholder*='Søg']:visible").first
        try:
            await search_input.wait_for(state="visible", timeout=10000)
            await search_input.fill("datatekniker")
            await page.keyboard.press("Enter")
        except Exception:
            first_input = page.locator("input:visible").first
            try:
                await first_input.wait_for(state="visible", timeout=10000)
                await first_input.fill("datatekniker")
                await page.keyboard.press("Enter")
            except Exception as e:
                logger.warning(f"Could not find search input on Jobnet: {e}")
                
        # Wait up to 8 seconds for interception to complete
        for _ in range(16):
            if intercepted_data:
                break
            await asyncio.sleep(0.5)
            
        if intercepted_data and "JobPositionPostings" in intercepted_data:
            for item in intercepted_data["JobPositionPostings"]:
                title = item.get("Title", "")
                company = item.get("CompanyName", "Ukendt")
                postal = str(item.get("ZipCode", ""))
                
                if is_valid_job(title, postal, company):
                    jobs.append(format_job(
                        job_id=item.get("ID"),
                        title=title,
                        company=company,
                        url=f"https://jobnet.dk/CV/FindWork/Details/{item.get('ID')}",
                        source="Jobnet"
                    ))
    except Exception as e:
        logger.error(f"Error in Jobnet scraper: {e}")
    finally:
        page.remove_listener("response", handle_response)
        
    return jobs

async def scrape_jobindex(page: Page) -> list[dict]:
    jobs = []
    try:
        logger.info("Starting Jobindex scrape...")
        await page.goto("https://www.jobindex.dk/jobsoegning/it/midtjylland?q=datatekniker", timeout=30000)
        try:
            await page.wait_for_selector(".jobsearch-result", timeout=10000)
        except Exception:
            logger.warning("No jobsearch-result found on Jobindex.")
            return jobs
            
        listings = await page.locator(".jobsearch-result").all()
        for listing in listings:
            title_el = listing.locator("h4 a").first
            if not await title_el.count():
                continue
                
            title = await title_el.inner_text()
            url = await title_el.get_attribute("href")
            
            if url and "?" in url:
                url = url.split("?")[0]
            
            company = "Ukendt"
            company_el = listing.locator(".jix_robotjob--company strong, .company-name").first
            if await company_el.count():
                company = await company_el.inner_text()
                
            # Safely check for area element count to avoid 30s timeout
            area_el = listing.locator(".jix_robotjob--area, .area").first
            postal = ""
            if await area_el.count() > 0:
                location_text = await area_el.inner_text()
                postal_match = re.search(r'\b(\d{4})\b', location_text)
                postal = postal_match.group(1) if postal_match else ""
            
            if is_valid_job(title, postal, company):
                job_id = url.split("/")[-1] if url else title
                jobs.append(format_job(
                    job_id=job_id,
                    title=title,
                    company=company,
                    url=url,
                    source="Jobindex"
                ))
    except Exception as e:
        logger.error(f"Error in Jobindex scraper: {e}")
    return jobs

async def scrape_linkedin(page: Page) -> list[dict]:
    jobs = []
    try:
        logger.info("Starting LinkedIn scrape...")
        url = "https://www.linkedin.com/jobs/search?keywords=Datatekniker&location=Midtjylland%2C%20Denmark&f_TPR=r86400"
        await page.goto(url, timeout=30000)
        
        try:
            await page.wait_for_selector(".jobs-search__results-list li", timeout=10000)
        except Exception:
            logger.warning("No job results list found on LinkedIn.")
            return jobs
            
        listings = await page.locator(".jobs-search__results-list li").all()
        for listing in listings:
            title_el = listing.locator(".base-search-card__title").first
            if not await title_el.count():
                continue
                
            title = await title_el.inner_text()
            link_el = listing.locator(".base-card__full-link").first
            url = await link_el.get_attribute("href") if await link_el.count() else ""
            
            if url and "?" in url:
                url = url.split("?")[0]
                
            company_el = listing.locator(".base-search-card__subtitle").first
            company = await company_el.inner_text() if await company_el.count() else "Ukendt"
            
            if is_valid_job(title, "", company):
                job_id = url.split("-")[-1] if url else title
                jobs.append(format_job(
                    job_id=job_id,
                    title=title,
                    company=company,
                    url=url,
                    source="LinkedIn"
                ))
    except Exception as e:
        logger.error(f"Error in LinkedIn scraper: {e}")
    return jobs
