import re
import json
import asyncio
import os
import hashlib
from datetime import datetime, timezone
from patchright.async_api import Page
import httpx
import config
from config import logger
import functools

def with_error_screenshot(scraper_name: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(page: Page, *args, **kwargs):
            try:
                return await func(page, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {scraper_name} scraper: {e}")
                try:
                    os.makedirs("screenshots", exist_ok=True)
                    safe_name = scraper_name.replace(' ', '_').lower()
                    await page.screenshot(path=f"screenshots/{safe_name}_error.png")
                except Exception as se:
                    logger.error(f"Could not take screenshot for {scraper_name}: {se}")
                return []
        return wrapper
    return decorator

def is_valid_job(title: str, postal_code: str, company: str = "", location: str = "", bypass_geo: bool = False) -> bool:
    title_lower = title.lower()
    company_lower = company.lower()
    location_lower = location.lower()
    
    # Geolocation filtering
    is_in_region = bypass_geo
    if not is_in_region:
        if postal_code and postal_code.isdigit():
            if 7400 <= int(postal_code) <= 8999:
                is_in_region = True
        else:
            if config.CITY_PATTERN.search(location_lower) or "hele landet" in location_lower or "midtjylland" in location_lower or "jylland" in location_lower:
                is_in_region = True
                
    if not is_in_region:
        return False
            
    # Check hard exclusions first
    if config.EXCLUSION_PATTERN.search(title_lower):
        return False
        
    # Smart exclude: if title contains infrastruktur/support, it MUST also contain programming keywords
    has_target_skill = bool(config.TARGET_KEYWORD_PATTERN.search(title_lower))
    if ("infrastruktur" in title_lower or "support" in title_lower) and not has_target_skill:
        return False
            
    # Target enterprises logic
    is_target_enterprise = any(ent in company_lower for ent in config.TARGET_ENTERPRISES)

    # Check for target keywords using word boundaries to avoid false positives
    has_target_skill = bool(config.TARGET_KEYWORD_PATTERN.search(title_lower))
            
    is_elev = "datatekniker" in title_lower or any(e in title_lower for e in config.ELEV_KEYWORDS)
    is_it_role = "datatekniker" in title_lower or "it" in title_lower.split() or "it-" in title_lower or "data" in title_lower
    
    if is_target_enterprise and is_elev:
        return True
        
    if has_target_skill and is_elev:
        return True
        
    # Since we strictly filter out supporter/infrastructure/student jobs above, 
    # any remaining "datatekniker" or "IT-elev" role is highly likely relevant
    if is_elev and is_it_role:
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

@with_error_screenshot("Lærepladsen")
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
        logger.info("Scraping Lærepladsen...")
        page.on("response", handle_response)
        
        # Load the direct search page which automatically triggers the API GET request
        # Widened to include the entire Data- og kommunikationsuddannelsen category (3607)
        url = "https://sr.laerepladsen.dk/soeg-opslag/0/Data-%20og%20kommunikationsuddannelsen/3607/midtjylland"
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
    finally:
        page.remove_listener("response", handle_response)
        
    return jobs

@with_error_screenshot("Jobnet")
async def scrape_jobnet(page: Page) -> list[dict]:

    jobs = []
    logger.info("Scraping Jobnet...")
    await page.goto("https://jobnet.dk/find-job", wait_until="networkidle", timeout=30000)
    
    # Call BFF Search endpoint
    js_code = """
    async () => {
        const url = 'https://jobnet.dk/bff/FindJob/Search?resultsPerPage=100&pageNumber=1&orderType=BestMatch&searchString=datatekniker';
        const response = await fetch(url, {
            headers: {
                'x-csrf': '1',
                'accept': 'application/json'
            }
        });
        if (!response.ok) {
            throw new Error('HTTP error ' + response.status);
        }
        return await response.json();
    }
    """
    data = await page.evaluate(js_code)
    postings = data.get("jobAds", [])
    logger.info(f"Jobnet BFF API returned {len(postings)} postings")
    
    for item in postings:
        title = item.get("title", "") or item.get("occupation", "")
        company = item.get("hiringOrgName", "Ukendt")
        postal = str(item.get("postalCode", ""))
        job_id = str(item.get("jobAdId", ""))
        
        # Use external URL if available, otherwise construct standard Jobnet details URL
        external_url = item.get("jobAdUrl", "")
        url = external_url if (external_url and external_url.startswith("http")) else f"https://jobnet.dk/find-job/details/{job_id}"

        if is_valid_job(title, postal, company):
            jobs.append(format_job(
                job_id=job_id,
                title=title,
                company=company,
                url=url,
                source="Jobnet"
            ))
    return jobs

@with_error_screenshot("IT-Jobbank")
async def scrape_itjobbank(page: Page) -> list[dict]:

    jobs = []
    logger.info("Scraping IT-Jobbank...")
    for q in config.JOB_QUERIES:
        for page_num in range(1, 4):  # Check up to 3 pages
            url = f"https://www.it-jobbank.dk/job/midtjylland?q={q}&page={page_num}"
            await page.goto(url, wait_until="networkidle", timeout=30000)

            try:
                await page.wait_for_selector(".job-search-result, .job-item, .result-item", timeout=5000)
            except Exception:
                if page_num == 1:
                    logger.info(f"No job results found on IT-Jobbank for query '{q}'. Taking screenshot.")
                    try:
                        os.makedirs("screenshots", exist_ok=True)
                        await page.screenshot(path=f"screenshots/empty_itjobbank_{q}.png")
                    except Exception:
                        pass
                break  # Stop paginating if no results

            listings = await page.locator(".job-item, .result-item").all()
            if not listings:
                break
                
            logger.info(f"IT-Jobbank found {len(listings)} raw listings for query '{q}' on page {page_num}")
            for listing in listings:
                title_el = listing.locator("h3 a, h2 a, .job-title a").first
                if not await title_el.count():
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href") or ""
                job_url = href if href.startswith("http") else f"https://www.it-jobbank.dk{href}"
                
                if "?" in job_url and not "job=" in job_url:
                    job_url = job_url.split("?")[0]

                company_el = listing.locator(".company-name, .employer, .job-company").first
                company = (await company_el.inner_text()).strip() if await company_el.count() else "Ukendt"

                location_el = listing.locator(".job-location, .location").first
                location_text = (await location_el.inner_text()).strip() if await location_el.count() else ""
                
                postal_match = re.search(r'\b(\d{4})\b', location_text)
                postal = postal_match.group(1) if postal_match else ""

                if is_valid_job(title, postal, company, location_text):
                    job_id_str = f"{company}_{title}_{job_url}"
                    job_id = hashlib.md5(job_id_str.encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=title,
                        company=company,
                        url=job_url,
                        source="ITJobbank"
                    ))
    return jobs

async def scrape_thehub() -> list[dict]:

    jobs = []
    try:
        logger.info("Scraping TheHub.io...")
        api_url = "https://thehub.io/api/jobs"
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
        
        client_kwargs = {"timeout": 20.0, "follow_redirects": True}
        if config.PROXY_URL:
            client_kwargs["proxy"] = config.PROXY_URL
            
        async with httpx.AsyncClient(**client_kwargs) as client:
            # Search for both 'elev' and 'datatekniker'
            for term in ["elev", "datatekniker"]:
                params = {"countryCode": "DK", "search": term}
                resp = await client.get(api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    continue
                    
                data = resp.json()
                docs = data.get("docs", [])
                
                for item in docs:
                    title = item.get("title", "")
                    company_data = item.get("company", {})
                    company = company_data.get("name", "Ukendt") if isinstance(company_data, dict) else "Ukendt"
                    
                    postal = ""
                    locations = item.get("location")
                    if isinstance(locations, dict):
                        locations = [locations]
                    if isinstance(locations, list):
                        for loc in locations:
                            if isinstance(loc, dict) and loc.get("country") == "Denmark":
                                postal = str(loc.get("postalCode", ""))
                                break
                            
                    job_id = str(item.get("key", ""))
                    slug = item.get("slug", "")
                    company_slug = company_data.get("slug", "") if isinstance(company_data, dict) else ""
                    
                    if slug and company_slug:
                        url = f"https://thehub.io/jobs/{company_slug}/{slug}"
                    else:
                        url = f"https://thehub.io/jobs?jobId={job_id}"
                    
                    location_str = str(locations) if locations else ""
                    if is_valid_job(title, postal, company, location_str):
                        jobs.append(format_job(
                            job_id=job_id,
                            title=title,
                            company=company,
                            url=url,
                            source="TheHub"
                        ))
    except Exception as e:
        logger.error(f"Error in TheHub scraper: {e}")
    return jobs

@with_error_screenshot("Jobindex")
async def scrape_jobindex(page: Page) -> list[dict]:
    jobs = []
    logger.info("Scraping Jobindex...")
    for q in config.JOB_QUERIES:
        for page_num in range(1, 4): # check up to 3 pages
            url = f"https://www.jobindex.dk/jobsoegning/it/midtjylland?q={q}&page={page_num}"
            await page.goto(url, timeout=30000)
            try:
                await page.wait_for_selector(".jobsearch-result", timeout=10000)
            except Exception:
                if page_num == 1:
                    logger.warning(f"No jobsearch-result found on Jobindex for query '{q}'.")
                    try:
                        os.makedirs("screenshots", exist_ok=True)
                        await page.screenshot(path=f"screenshots/empty_jobindex_{q}.png")
                    except Exception:
                        pass
                break
                
            listings = await page.locator(".jobsearch-result").all()
            if not listings:
                break
                
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
                location_text = ""
                if await area_el.count() > 0:
                    location_text = await area_el.inner_text()
                    postal_match = re.search(r'\b(\d{4})\b', location_text)
                    postal = postal_match.group(1) if postal_match else ""
                
                if is_valid_job(title, postal, company, location_text):
                    job_id_str = f"{company}_{title}_{url}"
                    job_id = hashlib.md5(job_id_str.encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=title,
                        company=company,
                        url=url,
                        source="Jobindex"
                    ))
    return jobs

async def scrape_elevplads(page: Page) -> list[dict]:

    jobs = []
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    client_kwargs = {"timeout": 20.0, "follow_redirects": True}
    if config.PROXY_URL:
        client_kwargs["proxy"] = config.PROXY_URL
        
    async with httpx.AsyncClient(**client_kwargs) as client:
        for q in config.JOB_QUERIES:
            try:
                logger.info(f"Scraping Elevplads.dk for '{q}'...")
                api_url = "https://elevplads.dk/api/posts/get-vacancies"
                params = {
                    "query": q,
                    "future_only": "false",
                    "page": 1,
                    "sort": "recommended"
                }
                resp = await client.get(api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"Elevplads.dk API returned {resp.status_code} for query '{q}'")
                    continue
                    
                data = resp.json()
                posts = data.get("posts", [])
                logger.info(f"Elevplads.dk returned {len(posts)} posts for query '{q}'")
                
                for post in posts:
                    title = post.get("title", "")
                    company = post.get("company_name", "") or "Ukendt"
                    location = post.get("working_place", "")
                    job_id = str(post.get("id", ""))
                    link = post.get("link", "")
                    url = f"https://elevplads.dk{link}" if link else "https://elevplads.dk/find-elevplads"
                    
                    postal_match = re.search(r'\b(\d{4})\b', location)
                    postal = postal_match.group(1) if postal_match else ""
                    
                    if is_valid_job(title, postal, company, location):
                        jobs.append(format_job(
                            job_id=job_id,
                            title=title,
                            company=company,
                            url=url,
                            source="Elevplads"
                        ))
            except Exception as e:
                logger.error(f"Error in elevplads scraper for query '{q}': {e}")
                
    return jobs
