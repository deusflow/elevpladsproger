import re
import json
import asyncio
import os
import urllib.parse
from typing import Any, Optional
import hashlib
from datetime import datetime, timezone
import httpx
try:
    from patchright.async_api import Page  # type: ignore
except ImportError:
    try:
        from playwright.async_api import Page  # type: ignore
    except ImportError:
        Page = Any  # type: ignore
from bs4 import BeautifulSoup
import config
from config import logger
import functools
from utils import normalize_job_url, normalize_company_name

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
                    await page.screenshot(path=f"screenshots/{safe_name}_error.png", timeout=3000)
                except Exception as se:
                    logger.error(f"Could not take screenshot for {scraper_name}: {se}")
                # Return error marker so main.py can track scraper health
                return [{"type": "scraper_error", "source": scraper_name, "error": str(e)}]
        return wrapper
    return decorator

# Regions that are OUT of scope even though their text may appear without a
# postal code: Hovedstaden (Copenhagen), Sjælland, Bornholm. Note Funen
# (Odense/Svendborg/Nyborg/Middelfart) IS in scope since Region Syddanmark
# joined the target regions.
NON_TARGET_REGION_PATTERN = re.compile(
    r'\b(?:københavn|copenhagen|storkøbenhavn|hovedstaden|frederiksberg|nordsjælland|sjælland|roskilde|helsingør|hillerød|lyngby|ballerup|taastrup|glostrup|herlev|hvidovre|brøndby|albertslund|ishøj|greve|køge|bornholm)\b',
    re.IGNORECASE
)

# Backwards-compatible alias used by earlier versions / downstream imports.
NON_MIDTJYLLAND_PATTERN = NON_TARGET_REGION_PATTERN

def is_valid_job(title: str, postal_code: str, company: str = "", location: str = "", bypass_geo: bool = False, trusted_region: bool = False, extra_text: str = "") -> bool:
    title_lower = title.lower()
    company_lower = company.lower()
    location_lower = location.lower()
    # extra_text acts as supplementary POSITIVE signal ONLY (e.g. the Jobnet ad
    # body). It is never used for exclusions — bodies often mention words like
    # "support" for roles that are perfectly relevant.
    extra_text_lower = re.sub(r"<[^>]+>", " ", (extra_text or "")).lower()

    # 1. Geolocation filtering
    is_in_region = bypass_geo
    if not is_in_region:
        if postal_code and postal_code.isdigit():
            if postal_code in config.TARGET_POSTAL_CODES:
                is_in_region = True
        else:
            # Exclude explicit non-target regions (Copenhagen, Sjælland, Bornholm)
            if NON_TARGET_REGION_PATTERN.search(location_lower) or NON_TARGET_REGION_PATTERN.search(title_lower):
                return False

            if (config.CITY_PATTERN.search(location_lower) or
                config.CITY_PATTERN.search(title_lower) or
                config.CITY_PATTERN.search(company_lower) or
                "hele landet" in location_lower or "midtjylland" in location_lower or
                "jylland" in location_lower or "danmark" in location_lower or
                "remote" in location_lower or "hjemmearbejde" in location_lower):
                is_in_region = True
            elif trusted_region:
                # The source search was already scoped to the target regions and
                # the location is inconclusive (e.g. a small town not in our
                # city list and no postal code) — trust the source filter
                # rather than drop it.
                is_in_region = True
                
    if not is_in_region:
        return False
            
    # 2. Hard exclusions (studentermedhjælper, unpaid internships, studiejob)
    if getattr(config, "HARD_EXCLUSION_PATTERN", None) and config.HARD_EXCLUSION_PATTERN.search(title_lower):
        return False

    # Support exclusion: only exclude pure IT-support / helpdesk roles that have
    # NO programming / software / datatekniker / security signal.
    if getattr(config, "SUPPORT_EXCLUSION_PATTERN", None) and config.SUPPORT_EXCLUSION_PATTERN.search(title_lower):
        has_dev_or_datatekniker = any(k in title_lower for k in config.ROLE_OVERRIDE_KEYWORDS)
        if not has_dev_or_datatekniker:
            return False
    elif config.EXCLUSION_PATTERN.search(title_lower):
        return False

    # 3. MUST be an elevplads / apprenticeship / trainee / datatekniker.
    # If the title carries no elev/datatekniker signal, fall back to the ad
    # body (extra_text) — e.g. a Jobnet ad titled just "Datatekniker" whose
    # description explicitly says "elevplads"/"lærling".
    title_is_elev = "datatekniker" in title_lower or any(e in title_lower for e in config.ELEV_KEYWORDS)
    is_elev = title_is_elev
    if not is_elev and extra_text_lower:
        # Body text accepts ONLY explicit apprenticeship wording
        # (ELEV_BODY_PATTERN): a plain substring scan is wrong because English
        # words like "relevant" embed the Danish stem "elev", bodies mention
        # "elever" (pupils) ubiquitously and "datatekniker" is usually a
        # required EDUCATION, not an offer of an elevplads.
        elev_body_pattern = getattr(config, "ELEV_BODY_PATTERN", None)
        if elev_body_pattern is not None and elev_body_pattern.search(extra_text_lower):
            is_elev = True
    if not is_elev:
        return False
    elev_signal_from_body = is_elev and not title_is_elev

    # 4. Target Enterprise or Target IT Skill or General IT Role
    is_target_enterprise = any(ent in company_lower for ent in config.TARGET_ENTERPRISES)
    has_target_skill = bool(config.TARGET_KEYWORD_PATTERN.search(title_lower))
    # "it-" with a word boundary: a plain substring check also matches inside
    # words like "merit-elever" (m-e-r-i-t-) and wrongly gates them through.
    has_it_prefix_token = bool(re.search(r'\bit-', title_lower))
    is_it_role = (
        "datatekniker" in title_lower or
        "it" in title_lower.split() or
        has_it_prefix_token or
        "software" in title_lower or
        "programm" in title_lower or
        "cyber" in title_lower or
        "apprentice" in title_lower or
        # A technical/specialisation word in the title plus an explicit
        # apprenticeship signal in the body makes the role a plausible
        # Datatekniker match (e.g. "Netværkstekniker" whose body explicitly
        # offers en elevplads). Generic trades ("bagerlærling",
        # "elektrikerlærling", school-teacher ads mentioning "elever") have
        # none of these specialisation words and stay excluded.
        (
            elev_signal_from_body and (
                any(k in title_lower for k in config.PROGRAMMING_KEYWORDS) or
                any(k in title_lower for k in config.SECURITY_KEYWORDS) or
                any(k in title_lower for k in config.INFRA_KEYWORDS)
            )
        )
    )

    if is_target_enterprise:
        # Require IT relevance even for target enterprises to filter out dairy, warehouse, or sales apprentices
        return bool(has_target_skill or is_it_role)
        
    if has_target_skill:
        return True
        
    if is_it_role:
        return True
        
    return False

# Ranking of a job title against the desired Datatekniker focus.
# 3 = programming / software development (main focus)
# 2 = cybersecurity / IT-security
# 1 = Datatekniker (generic) / infrastructure & operations
# 0 = other/generic IT
PRIORITY_LABELS = {
    3: "💻 Programmering",
    2: "🔐 Cybersikkerhed",
    1: "🖥️ Infrastruktur/Drift",
    0: "ℹ️ IT",
}


def job_priority(title: str) -> int:
    """Rank a job title by how well it matches the Datatekniker-Programmering focus."""
    t = (title or "").lower()
    if any(k in t for k in config.PROGRAMMING_KEYWORDS):
        return 3
    if any(k in t for k in config.SECURITY_KEYWORDS):
        return 2
    if "datatekniker" in t or any(k in t for k in config.INFRA_KEYWORDS):
        return 1
    return 0


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
async def scrape_laerepladsen(page: Optional[Page] = None) -> list[dict]:
    import laerepladsen_radar
    active_jobs, _ = await laerepladsen_radar.fetch_laerepladsen_all()
    return active_jobs


@with_error_screenshot("Jobnet")
async def scrape_jobnet(page: Page) -> list[dict]:

    jobs = []
    logger.info("Scraping Jobnet across all JOB_QUERIES...")
    await page.goto("https://jobnet.dk/find-job", wait_until="domcontentloaded", timeout=30000)
    
    seen_ids = set()
    for q in config.JOB_QUERIES:
        try:
            q_encoded = urllib.parse.quote(q)
            # The BFF supports a server-side region filter via repeated
            # `regions` params (verified live: regions=Midtjylland&regions=
            # Nordjylland correctly unions both regions). Without it every
            # query spans all of Denmark and a regional ad ranked beyond the
            # first 100 results is silently lost. Scope every query to ALL
            # target regions and page through the complete result set.
            regions_param = "&".join(f"regions={r}" for r in config.TARGET_REGIONS)
            for page_num in range(1, 6):
                js_code = f"""
                async () => {{
                    const url = 'https://jobnet.dk/bff/FindJob/Search?resultsPerPage=100&pageNumber={page_num}&orderType=BestMatch&searchString={q_encoded}&{regions_param}';
                    const response = await fetch(url, {{
                        headers: {{
                            'x-csrf': '1',
                            'accept': 'application/json'
                        }}
                    }});
                    if (!response.ok) {{
                        return {{ jobAds: [], totalJobAdCount: 0 }};
                    }}
                    return await response.json();
                }}
                """
                data = await page.evaluate(js_code)
                postings = data.get("jobAds", [])
                regional_total = int(data.get("totalJobAdCount") or 0)
                logger.info(f"Jobnet returned {len(postings)} regional postings for '{q}' (page {page_num}, total {regional_total})")

                for item in postings:
                    job_id = str(item.get("jobAdId", ""))
                    if not job_id or job_id in seen_ids:
                        continue

                    title = item.get("title", "") or item.get("occupation", "")
                    company = item.get("hiringOrgName", "Ukendt")
                    postal = str(item.get("postalCode", ""))
                    workplace = item.get("workplaceAddress", {})
                    location = ""
                    if isinstance(workplace, dict):
                        if not postal:
                            postal = str(workplace.get("postalCode", ""))
                        location = str(workplace.get("city", ""))
                    if not location:
                        # Jobnet BFF exposes postalDistrictName / municipality, not "city"
                        location = str(
                            item.get("postalDistrictName")
                            or item.get("municipality")
                            or item.get("city")
                            or ""
                        )

                    # Use external URL if available, otherwise construct standard Jobnet details URL
                    external_url = item.get("jobAdUrl", "")
                    url = external_url if (external_url and external_url.startswith("http")) else f"https://jobnet.dk/find-job/details/{job_id}"

                    if is_valid_job(
                        title, postal, company, location=location,
                        extra_text=str(item.get("description", "") or "")
                    ):
                        seen_ids.add(job_id)
                        jobs.append(format_job(
                            job_id=job_id,
                            title=title,
                            company=company,
                            url=url,
                            source="Jobnet"
                        ))

                if not postings or len(postings) < 100 or page_num * 100 >= regional_total:
                    break
        except Exception as e:
            logger.warning(f"Error querying Jobnet for '{q}': {e}")

    return jobs

# Consolidated query stems for browser aggregators (Jobindex & IT-Jobbank).
# Stemming on Jobindex/IT-Jobbank automatically covers inflections:
# "datatekniker" covers datatekniker, datateknikerelev, datateknikerlærling
# "apprentice" covers software apprentice, it apprentice, developer apprentice
AGGREGATOR_QUERIES = [
    "datatekniker",
    "it-elev",
    "programmørelev",
    "software elev",
    "it-lærling",
    "elevplads it",
    "apprentice"
]


@with_error_screenshot("IT-Jobbank")
async def scrape_itjobbank(page: Page) -> list[dict]:
    jobs = []
    seen_job_ids = set()
    logger.info("Scraping IT-Jobbank...")
    for q in AGGREGATOR_QUERIES:
        for page_num in range(1, 4):  # Check up to 3 pages
            url = f"https://www.it-jobbank.dk/jobsoegning?q={q}&page={page_num}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_selector(".jobsearch-result, .PaidJob, #jobsearch-app, .job-item, .result-item", timeout=8000)
            except Exception:
                pass

            # Fast check if zero results using window.Stash or page text
            hitcount = await page.evaluate("""() => {
                try {
                    return window.Stash?.['jobsearch/result_app']?.storeData?.searchResponse?.hitcount ?? null;
                } catch(e) { return null; }
            }""")
        
            page_text = await page.inner_text("body")
            if hitcount == 0 or "0 job" in page_text.lower() or "ingen ledige" in page_text.lower() or "ingen resultater" in page_text.lower():
                if page_num == 1:
                    logger.info(f"IT-Jobbank confirmed 0 results for query '{q}'.")
                break

            listings = await page.locator(".jobsearch-result, .PaidJob, .job-item, .result-item").all()
            if not listings:
                if page_num == 1:
                    logger.warning(f"IT-Jobbank selectors not found for query '{q}' — site may have changed layout.")
                    try:
                        os.makedirs("screenshots", exist_ok=True)
                        await page.screenshot(path=f"screenshots/empty_itjobbank_{q}.png", timeout=3000)
                    except Exception as se:
                        logger.debug(f"Screenshot failed for IT-Jobbank: {se}")
                break
            
            logger.info(f"IT-Jobbank found {len(listings)} raw listings for query '{q}' on page {page_num}")
            for listing in listings:
                title_el = listing.locator("h4 a, h3 a, h2 a, .job-title a, a[data-click*='job-title']").first
                if not await title_el.count():
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href") or ""
                job_url = href if href.startswith("http") else f"https://www.it-jobbank.dk{href}"
            
                if "?" in job_url and not "job=" in job_url:
                    job_url = job_url.split("?")[0]

                company_el = listing.locator(".company-name, .employer, .job-company, .jix_robotjob--company strong, a[data-click*='company-name']").first
                company = (await company_el.inner_text()).strip() if await company_el.count() else "Ukendt"

                location_el = listing.locator(".job-location, .location, .area, .jix_robotjob--area").first
                location_text = (await location_el.inner_text()).strip() if await location_el.count() else ""
            
                postal_match = re.search(r'\b(\d{4})\b', location_text)
                postal = postal_match.group(1) if postal_match else ""

                if is_valid_job(title, postal, company, location_text):
                    clean_c = normalize_company_name(company)
                    clean_u = normalize_job_url(job_url)
                    clean_t = re.sub(r'\s+', ' ', title.strip().lower())
                    job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                    if job_id not in seen_job_ids:
                        seen_job_ids.add(job_id)
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
        api_url = "https://api.thehub.io/v2/jobs"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        
        client_kwargs: dict[str, Any] = {"timeout": 20.0, "follow_redirects": True}
        if config.PROXY_URL:
            client_kwargs["proxy"] = config.PROXY_URL
            
        async with httpx.AsyncClient(**client_kwargs) as client:
            # Search for both 'elev' and 'datatekniker'
            for term in ["elev", "datatekniker"]:
                params = {"countryCode": "DK", "search": term, "limit": 50}
                resp = await client.get(api_url, params=params, headers=headers)
                if resp.status_code != 200:
                    logger.warning(f"TheHub API v2 returned {resp.status_code} for search='{term}'")
                    continue
                    
                data = resp.json()
                docs = data.get("docs", [])
                logger.info(f"TheHub API v2 returned {len(docs)} results for search='{term}'")
                
                for item in docs:
                    title = item.get("title", "")
                    company_data = item.get("company", {})
                    company = company_data.get("name", "Ukendt") if isinstance(company_data, dict) else "Ukendt"
                    
                    postal = ""
                    location = item.get("location")
                    locations = [location] if isinstance(location, dict) else (location if isinstance(location, list) else [])
                    for loc in locations:
                        if isinstance(loc, dict) and loc.get("country") == "Denmark":
                            postal = str(loc.get("postalCode", ""))
                            break
                            
                    job_id = str(item.get("id", item.get("key", "")))
                    job_key = item.get("key", "")
                    company_key = company_data.get("key", "") if isinstance(company_data, dict) else ""
                    
                    if job_key and company_key:
                        url = f"https://thehub.io/jobs/{company_key}/{job_key}"
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
        return [{"type": "scraper_error", "source": "TheHub", "error": str(e)}]
    return jobs

@with_error_screenshot("Jobindex")
async def scrape_jobindex(page: Page) -> list[dict]:
    jobs = []
    seen_job_ids = set()
    logger.info("Scraping Jobindex...")
    for q in AGGREGATOR_QUERIES:
        for region_slug in getattr(config, "TARGET_REGION_SLUGS", ["region-midtjylland"]):
            for page_num in range(1, 4): # check up to 3 pages
                url = f"https://www.jobindex.dk/jobsoegning/it/{region_slug}?q={q}&page={page_num}"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    # PaidJob is the primary class used in Jobindex SSR rendering
                    await page.wait_for_selector(".PaidJob, .jobsearch-result", timeout=8000)
                except Exception as e:
                    # Distinguish "no results" from "site changed layout"
                    page_text = await page.inner_text("body")
                    if "ingen resultater" in page_text.lower() or "0 job" in page_text.lower() or "ingen ledige" in page_text.lower():
                        if page_num == 1:
                            logger.info(f"Jobindex confirmed 0 results for query '{q}'.")
                    else:
                        if page_num == 1:
                            logger.warning(f"Jobindex selectors not found for query '{q}' — site may have changed layout. Error: {e}")
                            try:
                                os.makedirs("screenshots", exist_ok=True)
                                await page.screenshot(path=f"screenshots/empty_jobindex_{q}.png", timeout=3000)
                            except Exception as se:
                                logger.debug(f"Screenshot failed for Jobindex: {se}")
                    break
                
                listings = await page.locator(".PaidJob, .jobsearch-result").all()
                if not listings:
                    break
                
                for listing in listings:
                    title_el = listing.locator("h4 a, h3 a, .job-title a").first
                    if not await title_el.count():
                        continue
                    
                    title = await title_el.inner_text()
                    job_url: Optional[str] = await title_el.get_attribute("href")
                    if not job_url:
                        continue
                
                    if job_url and "?" in job_url:
                        job_url = job_url.split("?")[0]
                
                    company = "Ukendt"
                    company_el = listing.locator(
                        ".jix-toolbar-top__company a, .jix-toolbar-top__company, "
                        ".jix_robotjob--company strong, .company-name, [class*='company'] strong"
                    ).first
                    if await company_el.count():
                        company = (await company_el.inner_text()).strip() or "Ukendt"
                    
                    # Safely check for area element count to avoid 30s timeout
                    area_el = listing.locator(".jix_robotjob--area, .area").first
                    postal = ""
                    location_text = ""
                    if await area_el.count() > 0:
                        location_text = await area_el.inner_text()
                        postal_match = re.search(r'\b(\d{4})\b', location_text)
                        postal = postal_match.group(1) if postal_match else ""
                
                    if is_valid_job(title, postal, company, location_text, trusted_region=True):
                        clean_c = normalize_company_name(company)
                        clean_u = normalize_job_url(job_url)
                        clean_t = re.sub(r'\s+', ' ', title.strip().lower())
                        job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                        if job_id not in seen_job_ids:
                            seen_job_ids.add(job_id)
                            jobs.append(format_job(
                                job_id=job_id,
                                title=title,
                                company=company,
                                url=job_url,
                                source="Jobindex"
                            ))
    return jobs

async def scrape_elevplads() -> list[dict]:
    """Scrape Elevplads.dk.

    The portal's free-text search is unreliable (e.g. "datatekniker" returns 0
    results), so we download the full vacancy feed once and filter locally.
    This guarantees no relevant posting is missed because of weak API matching.
    """
    jobs = []
    seen_ids = set()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    client_kwargs: dict[str, Any] = {"timeout": 20.0, "follow_redirects": True}
    if config.PROXY_URL:
        client_kwargs["proxy"] = config.PROXY_URL

    api_url = "https://elevplads.dk/api/posts/get-vacancies"
    page_size = 15
    max_pages = 60

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            base_params = {"query": "", "future_only": "false", "sort": "recommended"}

            first = await client.get(api_url, params={**base_params, "page": 1}, headers=headers)
            if first.status_code != 200:
                logger.warning(f"Elevplads.dk API returned {first.status_code}")
                return []

            first_data = first.json()
            posts = list(first_data.get("posts", []))
            total = int(first_data.get("post_count") or 0)
            total_pages = min(max(1, (total + page_size - 1) // page_size), max_pages)
            logger.info(f"Elevplads.dk reports {total} vacancies across {total_pages} pages")

            sem = asyncio.Semaphore(6)

            async def fetch_page(pg: int) -> list[dict]:
                async with sem:
                    try:
                        r = await client.get(api_url, params={**base_params, "page": pg}, headers=headers)
                        if r.status_code == 200:
                            return r.json().get("posts", [])
                        logger.warning(f"Elevplads.dk page {pg} returned {r.status_code}")
                    except Exception as e:
                        logger.warning(f"Error fetching Elevplads.dk page {pg}: {e}")
                    return []

            if total_pages > 1:
                tasks = [fetch_page(p) for p in range(2, total_pages + 1)]
                for page_posts in await asyncio.gather(*tasks):
                    posts.extend(page_posts)

        logger.info(f"Elevplads.dk returned {len(posts)} total vacancies")
        for post in posts:
            job_id = str(post.get("id", ""))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            title = post.get("title", "")
            company = post.get("company_name", "") or "Ukendt"
            location = post.get("working_place", "")
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
        return jobs
    except Exception as e:
        logger.error(f"Error in Elevplads scraper: {e}")
        return [{"type": "scraper_error", "source": "Elevplads", "error": str(e)}]

@with_error_screenshot("TechJob")
async def scrape_techjob(page: Page) -> list[dict]:
    """Scrape specialized tech jobs and apprenticeships from TechJob.dk (Ingeniøren / Version2)."""
    jobs = []
    logger.info("Scraping TechJob.dk...")
    # TechJob.dk is Ingeniøren's job board. Its content search (/sog?query=)
    # searches editorial articles, NOT jobs, so it always returned zero results.
    # Real job listings live under /jobs (paginated). We iterate the most recent
    # pages and let is_valid_job keep only genuine elevplads / apprenticeship roles.
    for page_num in range(0, 6):
        try:
            url = f"https://techjob.dk/jobs?page={page_num}"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            try:
                await page.wait_for_selector("article, .job-item, .views-row", timeout=8000)
            except Exception:
                break

            cards = await page.locator("article, .job-item, .views-row").all()
            if not cards:
                break

            for card in cards:
                title_el = card.locator(".job-title a, h2 a, h3 a, h4 a, a[href*='/job/']").first
                if not await title_el.count():
                    continue
                title = (await title_el.inner_text()).strip()
                href = await title_el.get_attribute("href") or ""
                job_url = href if href.startswith("http") else f"https://techjob.dk{href}"

                company_el = card.locator(
                    ".additional-info--company a, .additional-info--company, "
                    ".company, .company-name, [class*='company']"
                ).first
                company = (await company_el.inner_text()).strip() if await company_el.count() else "Ukendt"

                loc_el = card.locator(".additional-info--location, .location, .city, [class*='location'], .area").first
                location_text = (await loc_el.inner_text()).strip() if await loc_el.count() else ""

                postal_match = re.search(r'\b(\d{4})\b', location_text)
                postal = postal_match.group(1) if postal_match else ""

                if is_valid_job(title, postal, company, location_text):
                    clean_c = normalize_company_name(company)
                    clean_u = normalize_job_url(job_url)
                    clean_t = re.sub(r'\s+', ' ', title.strip().lower())
                    job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=title,
                        company=company,
                        url=job_url,
                        source="TechJob"
                    ))
        except Exception as e:
            logger.warning(f"Error querying TechJob.dk page {page_num}: {e}")

    return jobs

async def scrape_linkedin() -> list[dict]:
    """Scrape public LinkedIn job listings in Denmark / Midtjylland for apprenticeships and elevpladser."""
    jobs = []
    logger.info("Scraping LinkedIn Denmark Jobs...")
    queries = ["datatekniker", "it elev", "software elev", "elev programmering", "lærling it", "trainee software", "it-lærling"]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        "Accept-Language": "da-DK,da;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    client_kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
    if config.PROXY_URL:
        client_kwargs["proxy"] = config.PROXY_URL
        
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            for q in queries:
                try:
                    # LinkedIn guest search API with geoId=104514075 (Denmark)
                    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={urllib.parse.quote(q)}&location=Danmark&geoId=104514075&f_TPR=r2592000"
                    resp = await client.get(url, headers=headers)
                    if resp.status_code != 200:
                        logger.debug(f"LinkedIn guest endpoint returned {resp.status_code} for '{q}'")
                        continue
                    
                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.select("li, .job-search-card, .base-search-card")
                    
                    for card in cards:
                        title_el = card.select_one(".base-search-card__title, h3")
                        comp_el = card.select_one(".base-search-card__subtitle, h4")
                        loc_el = card.select_one(".job-search-card__location, span[class*='location']")
                        link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
                        
                        if not title_el or not link_el:
                            continue
                            
                        title = title_el.get_text(strip=True)
                        company = comp_el.get_text(strip=True) if comp_el else "Ukendt"
                        location_text = loc_el.get_text(strip=True) if loc_el else ""
                        href = link_el["href"] if "href" in link_el.attrs else ""
                        
                        # Clean tracking params from URL
                        clean_job_url = href.split("?")[0] if "?" in href else href
                        
                        postal_match = re.search(r'\b(\d{4})\b', location_text)
                        postal = postal_match.group(1) if postal_match else ""
                        
                        if is_valid_job(title, postal, company, location_text):
                            clean_c = normalize_company_name(company)
                            clean_u = normalize_job_url(clean_job_url)
                            clean_t = re.sub(r'\s+', ' ', title.strip().lower())
                            job_id = hashlib.md5(f"linkedin_{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                            jobs.append(format_job(
                                job_id=job_id,
                                title=title,
                                company=company,
                                url=clean_job_url,
                                source="LinkedIn"
                            ))
                except Exception as e:
                    logger.warning(f"Error querying LinkedIn for '{q}': {e}")
                await asyncio.sleep(0.5)
        return jobs
    except Exception as e:
        logger.error(f"Error in LinkedIn scraper: {e}")
        return [{"type": "scraper_error", "source": "LinkedIn", "error": str(e)}]
