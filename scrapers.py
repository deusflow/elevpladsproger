import re
import json
import asyncio
from datetime import datetime, timezone
from patchright.async_api import Page
import httpx
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
    """Uses page.evaluate() within the Playwright browser to query Jobnet's BFF search API."""
    jobs = []
    try:
        logger.info("Starting Jobnet scrape via browser BFF evaluation...")
        await page.goto("https://jobnet.dk/find-job", wait_until="networkidle", timeout=30000)
        
        # Call the BFF Search endpoint inside the authenticated browser context
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
    except Exception as e:
        logger.error(f"Error in Jobnet scraper: {e}")
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

async def scrape_elevplads(page: Page) -> list[dict]:
    """Uses elevplads.dk's public API to search for IT elevpladser — no browser needed."""
    jobs = []
    queries = ["datatekniker", "it-elev", "softwareudvikler", "udvikler-elev", "programmering"]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for q in queries:
            try:
                logger.info(f"Starting elevplads.dk scrape for query '{q}'...")
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
                    
                    is_in_region = False
                    location_lower = location.lower()
                    midtjylland_keywords = [
                        "midtjylland", "østjylland", "vestjylland", "aarhus", "randers", 
                        "horsens", "herning", "silkeborg", "viborg", "holstebro", "skive",
                        "skanderborg", "ikast", "grenaa", "struer", "odder", "bjerringbro",
                        "hammel", "hadsten", "hinnerup", "lemvig", "ringkøbing"
                    ]
                    
                    if postal:
                        if 7400 <= int(postal) <= 8999:
                            is_in_region = True
                    else:
                        if any(kw in location_lower for kw in midtjylland_keywords) or "hele landet" in location_lower:
                            is_in_region = True
                            
                    if is_in_region and is_valid_job(title, postal, company):
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
