import json
import logging
import asyncio
import os
import re
import hashlib
from typing import Optional, Any
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
try:
    from patchright.async_api import BrowserContext, Page  # type: ignore
except ImportError:
    try:
        from playwright.async_api import BrowserContext, Page  # type: ignore
    except ImportError:
        BrowserContext = Any  # type: ignore
        Page = Any  # type: ignore
import config
from scrapers import format_job, is_valid_job
from utils import normalize_job_url, normalize_company_name, extract_json_payload
from tenacity import retry, stop_after_attempt, wait_fixed
try:
    from playwright_stealth import stealth_async  # type: ignore
except ImportError:
    async def stealth_async(page): pass

logger = logging.getLogger("elevplads_scraper")

async def extract_links_from_frame(frame, base_url, found_jobs):
    try:
        # Fast 1-pass execution inside browser context (avoids heavy Playwright IPC calls)
        links_data = await frame.evaluate("""() => {
            return Array.from(document.querySelectorAll('a')).map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.getAttribute('href') || ''
            })).filter(l => l.text && l.href);
        }""")
        
        for link in links_data:
            text_lower = link["text"].lower()
            href = link["href"]
            if any(kw in text_lower for kw in ["datatekniker", "it-elev", "elevplads", "softwareudvikler", "cybersikkerhed", "it-sikkerhed"]):
                if href.startswith("http"):
                    job_url = href
                else:
                    job_url = base_url.rstrip("/") + "/" + href.lstrip("/")
                
                found_jobs.append({
                    "title": f"Mulig stilling: {link['text']}",
                    "url": job_url
                })
    except Exception as e:
        logger.debug(f"Failed to extract links from frame: {e}")
        
    for child in frame.child_frames:
        await extract_links_from_frame(child, base_url, found_jobs)

async def extract_jobs_with_groq(company_name: str, page_url: str, page_text: str) -> tuple[list[dict], bool]:
    if not config.GROQ_API_KEY and not getattr(config, "GEMINI_API_KEY", None):
        return [], False

    # Keyword pre-filter to avoid burning Groq tokens on pages without relevant keywords
    keywords = ["elev", "lærling", "trainee", "uddannelse", "praktik", "uopfordret", "datatekniker", "softwareudvikler", "it-"]
    text_lower = page_text.lower()
    if not any(k in text_lower for k in keywords):
        return [], True
        
    truncated_text = page_text[:8000]
    
    prompt = f"""You are an IT job scraper for Denmark (Jutland + Funen: Midtjylland, Nordjylland and Syddanmark regions).
Analyze the following career page text for '{company_name}' ({page_url}).
Identify any IT apprenticeship, IT trainee, IT elevplads, Datatekniker (programmering, cybersikkerhed or infrastruktur), or Software developer elev jobs.

CRUCIAL: You must also look for "hidden" or unsolicited (uopfordret ansøgning) apprenticeship announcements. If a paragraph mentions sending an unsolicited CV or email for an IT-elev or datatekniker role, treat it as a valid job opening with the title "Uopfordret ansøgning: IT-Elev".

IMPORTANT Rules:
- Exclude IT supporter / helpdesk / servicedesk / user-support roles, and non-IT jobs.
- Keep Datatekniker roles including infrastruktur/drift (lower priority, but valid).
- Only return jobs that are IT elev / datatekniker / software development / cybersecurity / IT-drift (including unsolicited/hidden ones).

Respond ONLY with valid JSON matching this schema:
{{
  "jobs": [
    {{
      "title": "Job title or 'Uopfordret ansøgning: IT-Elev'",
      "url": "Direct link or page_url if not distinct"
    }}
  ]
}}
If no relevant IT elev / datatekniker jobs are found, return {{"jobs": []}}.

Page Text:
{truncated_text}
"""
    
    # 1. Fast Gemini extraction: gemini-2.5-flash-lite
    if getattr(config, "GEMINI_API_KEY", None):
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={config.GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(gemini_url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    result = extract_json_payload(content)
                    raw_jobs = result.get("jobs", []) if isinstance(result, dict) else []
                    extracted = []
                    for j in raw_jobs:
                        title = j.get("title", "").strip()
                        job_url = j.get("url", "").strip() or page_url
                        if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                            extracted.append({"title": title, "url": job_url})
                    if extracted:
                        logger.info(f"Gemini (gemini-2.5-flash-lite) extracted {len(extracted)} IT elev jobs for {company_name}")
                    return extracted, True
                elif resp.status_code in [429, 503]:
                    logger.warning(f"Gemini 2.5-flash-lite status {resp.status_code} for {company_name}, switching immediately to Groq...")
                else:
                    logger.warning(f"Gemini API error {resp.status_code} for {company_name}: {resp.text}")
        except Exception as e:
            logger.warning(f"Gemini exception for {company_name}: {e}, switching immediately to Groq...")

    # 2. Fast Groq fallback chain: llama-3.3-70b-versatile -> llama-3.1-8b-instant
    if config.GROQ_API_KEY:
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        for model_id in ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]:
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": "You are a precise JSON job extractor."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(groq_url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"]
                        result = extract_json_payload(content)
                        raw_jobs = result.get("jobs", []) if isinstance(result, dict) else []
                        extracted = []
                        for j in raw_jobs:
                            title = j.get("title", "").strip()
                            job_url = j.get("url", "").strip() or page_url
                            if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                                extracted.append({"title": title, "url": job_url})
                        if extracted:
                            logger.info(f"Groq LLM ({model_id}) extracted {len(extracted)} IT elev jobs for {company_name}")
                        return extracted, True
                    elif resp.status_code in [429, 503]:
                        logger.warning(f"Groq {resp.status_code} on {model_id} for {company_name}, switching immediately to next model...")
                        continue
                    else:
                        logger.warning(f"Groq API error {resp.status_code} on {model_id}: {resp.text}")
                        continue
            except Exception as e:
                logger.warning(f"Error invoking Groq LLM ({model_id}) for {company_name}: {e}")
                continue
        
    return [], False

async def _do_scrape_company(page: Page, url: str):
    response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    if response and response.status in [404, 410]:
        logger.warning(f"Company career page permanently unavailable ({response.status}) at {url}")
        return [], "", "", []
    if response and response.status >= 400:
        raise Exception(f"HTTP {response.status} returned for {url}")
    await page.wait_for_load_state("domcontentloaded")
    
    found_jobs: list[dict] = []
    await extract_links_from_frame(page.main_frame, url, found_jobs)
    
    # Strip noisy elements to reduce false positive structural changes
    await page.evaluate("""() => {
        const noisySelectors = ['header', 'footer', 'nav', 'aside', '.cookie-banner', '#cookie-consent'];
        document.querySelectorAll(noisySelectors.join(',')).forEach(el => el.remove());
    }""")

    # Extract clean content links snapshot for change detection
    extracted_links = await page.evaluate("""() => {
        const links = [];
        const seen = new Set();
        document.querySelectorAll('a').forEach(a => {
            const text = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
            const href = a.href || '';
            if (text.length > 3 && href.startsWith('http') && !seen.has(href)) {
                seen.add(href);
                links.push({text: text, url: href});
            }
        });
        return links;
    }""")
            
    # Target content area or fallback to main/article/body
    content_el = page.locator("main, article, [class*='job'], [class*='career'], [class*='stilling'], [id*='job'], [id*='career']")
    if await content_el.count() > 0:
        body_text = await content_el.first.inner_text()
    else:
        body_text = await page.inner_text("body")
    
    # Exact normalized content fingerprinting (headings + links + clean text)
    fingerprint_data = await page.evaluate("""() => {
        const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4, .job-title, .career-title')).map(el => (el.innerText || '').trim()).join('|');
        const jobLinks = Array.from(document.querySelectorAll('a')).map(a => (a.innerText || '').trim()).filter(t => t.length > 5).join('|');
        return headings + '||' + jobLinks;
    }""")
    
    clean_fingerprint = re.sub(r'\s+', '', fingerprint_data.lower())
    if not clean_fingerprint or len(clean_fingerprint) < 10:
        clean_fingerprint = re.sub(r'\s+', '', body_text.lower())
        
    structural_hash = hashlib.md5(clean_fingerprint.encode("utf-8")).hexdigest()
    
    return found_jobs, body_text, structural_hash, extracted_links


async def _scrape_company_with_browser_retry(context: BrowserContext, url: str) -> tuple[list[dict], str, str, list[dict]]:
    """Scrape company career page using headless browser with a fresh page instance on retry."""
    last_err: Optional[Exception] = None
    for attempt in range(1, 3):
        page = await context.new_page()
        try:
            await stealth_async(page)
            return await _do_scrape_company(page, url)
        except Exception as e:
            last_err = e
            logger.warning(f"Browser scrape attempt {attempt}/2 failed for {url}: {e}")
            if attempt < 2:
                await asyncio.sleep(2.0)
        finally:
            await page.close()
    if last_err:
        raise last_err
    return [], "", "", []


async def try_teamtailor_api(company_name: str, base_url: str) -> Optional[list[dict]]:
    """Fast, direct JSON API extraction for Teamtailor-powered Danish career sites."""
    clean_url = base_url.rstrip("/")
    if not clean_url.endswith("/jobs"):
        api_candidates = [f"{clean_url}/jobs.json", f"{clean_url}.json", f"{clean_url}/jobs/jobs.json"]
    else:
        api_candidates = [f"{clean_url}.json", f"{clean_url}/jobs.json"]
        
    for api_url in api_candidates:
        try:
            client_kwargs: dict[str, Any] = {"timeout": 8.0, "follow_redirects": True}
            if getattr(config, "PROXY_URL", None):
                client_kwargs["proxy"] = config.PROXY_URL
            async with httpx.AsyncClient(**client_kwargs) as client:
                resp = await client.get(api_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
                if resp.status_code == 200 and "application/json" in resp.headers.get("content-type", ""):
                    data = resp.json()
                    items = data.get("items", [])
                    jobs = []
                    links = []
                    for item in items:
                        title = item.get("title", "").strip()
                        link = item.get("url", "").strip()
                        if title and link:
                            links.append({"text": title, "url": link})
                            if is_valid_job(title, "", company_name, "", bypass_geo=True):
                                clean_c = normalize_company_name(company_name)
                                clean_u = normalize_job_url(link)
                                clean_t = title.strip().lower()
                                job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                                jobs.append(format_job(
                                    job_id=job_id,
                                    title=title,
                                    company=company_name,
                                    url=link,
                                    source="TeamtailorAPI"
                                ))
                    structural_hash = hashlib.md5("|".join(sorted(str(i.get("id") or i.get("title", "")) for i in items)).encode()).hexdigest()
                    jobs.append({
                        "type": "hash",
                        "company": company_name,
                        "url": base_url,
                        "hash": str(structural_hash),
                        "links": links,
                        "llm_verified": True
                    })
                    if any(j.get("type") != "hash" for j in jobs):
                        logger.info(f"Teamtailor API found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
                    return jobs
        except Exception:
            pass
    return None


async def try_emply_api(company_name: str, base_url: str) -> Optional[list[dict]]:
    """Fast, direct API extraction for Emply-powered Danish career sites and municipalities."""
    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": True}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(base_url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            html_text = resp.text

            # 1. Emply Integration API with sectionId
            section_match = re.search(r'sectionId[\'\":\s]+([a-f0-9\-]{36})', html_text, re.IGNORECASE)
            if section_match:
                section_id = section_match.group(1)
                p = urlparse(base_url)
                api_url = f"{p.scheme}://{p.netloc}/api/integration/vacancy/get-page"
                payload = {
                    "count": 50,
                    "filters": [],
                    "langCode": "da-DK",
                    "offset": 0,
                    "searchText": "",
                    "sectionId": section_id,
                    "sortByProjectDataId": "",
                    "sortAscending": False,
                    "light": False,
                    "isJobAgent": False,
                    "siteId": None
                }
                api_resp = await client.post(api_url, json=payload, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
                if api_resp.status_code == 200:
                    vacancies = api_resp.json().get("vacancies", [])
                    jobs = []
                    links = []
                    for v in vacancies:
                        title = v.get("title", "").strip()
                        short_id = v.get("shortId") or v.get("id")
                        title_slug = v.get("titleAsUrl", "")
                        direct_link = v.get("applyLink") or v.get("directLink") or v.get("externalCseAdLink")
                        if direct_link:
                            job_url = direct_link
                        elif title_slug and short_id:
                            job_url = f"{p.scheme}://{p.netloc}/ad/{title_slug}/{short_id}"
                        else:
                            job_url = base_url

                        if title:
                            links.append({"text": title, "url": job_url})

                        if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                            clean_c = normalize_company_name(company_name)
                            clean_u = normalize_job_url(job_url)
                            clean_t = title.strip().lower()
                            job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                            jobs.append(format_job(
                                job_id=job_id,
                                title=title,
                                company=company_name,
                                url=job_url,
                                source="EmplyAPI"
                            ))

                    structural_hash = hashlib.md5("|".join(sorted(str(v.get("id", v.get("title", ""))) for v in vacancies)).encode()).hexdigest()
                    jobs.append({
                        "type": "hash",
                        "company": company_name,
                        "url": base_url,
                        "hash": str(structural_hash),
                        "links": links
                    })
                    if any(j.get("type") != "hash" for j in jobs):
                        logger.info(f"Emply API found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
                    return jobs

            # 2. Embedded DYCON.EmplyData (e.g. Aarhus Universitet)
            dycon_match = re.search(r'DYCON\.EmplyData\.[^=]+=\s*(\[.*?\]);', html_text, re.DOTALL)
            if dycon_match:
                vacancies = json.loads(dycon_match.group(1))
                jobs = []
                links = []
                for v in vacancies:
                    title = v.get("title", "").strip()
                    link = v.get("link") or v.get("url") or ""
                    job_url = urljoin(base_url, link) if link else base_url
                    if title:
                        links.append({"text": title, "url": job_url})

                    loc = v.get("location")
                    postal = str(loc.get("zip", "")) if isinstance(loc, dict) else ""
                    if title and is_valid_job(title, postal, company_name, "", bypass_geo=True):
                        clean_c = normalize_company_name(company_name)
                        clean_u = normalize_job_url(job_url)
                        clean_t = title.strip().lower()
                        job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                        jobs.append(format_job(
                            job_id=job_id,
                            title=title,
                            company=company_name,
                            url=job_url,
                            source="EmplyAPI"
                        ))

                structural_hash = hashlib.md5("|".join(sorted(str(v.get("id", v.get("title", ""))) for v in vacancies)).encode()).hexdigest()
                jobs.append({
                    "type": "hash",
                    "company": company_name,
                    "url": base_url,
                    "hash": str(structural_hash),
                    "links": links,
                    "llm_verified": True
                })
                if any(j.get("type") != "hash" for j in jobs):
                    logger.info(f"Emply Data found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
                return jobs

    except Exception as e:
        logger.debug(f"try_emply_api error for {company_name}: {e}")
    return None


async def try_workday_api(company_name: str, base_url: str) -> Optional[list[dict]]:
    """Fast, direct API extraction for Workday-powered career sites (e.g. LEGO Group)."""
    if "myworkdayjobs.com" not in base_url and "lego" not in company_name.lower():
        return None

    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": True}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    try:
        api_url = "https://lego.wd103.myworkdayjobs.com/wday/cxs/lego/LEGO_External/jobs"
        payload = {
            "appliedFacets": {},
            "limit": 50,
            "offset": 0,
            "searchText": ""
        }
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(api_url, json=payload, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                postings = data.get("jobPostings", [])
                jobs = []
                links = []
                for p in postings:
                    title = p.get("title", "").strip()
                    ext_path = p.get("externalPath", "")
                    job_url = f"https://lego.wd103.myworkdayjobs.com/LEGO_External{ext_path}" if ext_path else base_url
                    if title:
                        links.append({"text": title, "url": job_url})
                    if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                        clean_c = normalize_company_name(company_name)
                        clean_u = normalize_job_url(job_url)
                        clean_t = title.strip().lower()
                        job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                        jobs.append(format_job(
                            job_id=job_id,
                            title=title,
                            company=company_name,
                            url=job_url,
                            source="WorkdayAPI"
                        ))
                structural_hash = hashlib.md5("|".join(sorted(str(p.get("bulletFields", [p.get("title")])) for p in postings)).encode()).hexdigest()
                jobs.append({
                    "type": "hash",
                    "company": company_name,
                    "url": base_url,
                    "hash": str(structural_hash),
                    "links": links,
                    "llm_verified": True
                })
                if any(j.get("type") != "hash" for j in jobs):
                    logger.info(f"Workday API found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
                return jobs
    except Exception as e:
        logger.debug(f"try_workday_api error for {company_name}: {e}")
    return None


async def try_signatur_api(company_name: str, base_url: str) -> Optional[list[dict]]:
    """Fast, direct HTTP extraction for Signatur.dk-hosted Danish municipal career portals."""
    if "portal.signatur.dk" not in base_url:
        return None

    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": True}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(base_url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            a_tags = soup.find_all("a", href=re.compile(r"JobDetails\.aspx|JobProfile\.aspx", re.I))
            jobs = []
            links = []
            seen_links = set()
            for a in a_tags:
                href = a.get("href", "")
                full_url = urljoin(base_url, href)
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)

                text = a.get_text(" ", strip=True)
                title_match = re.search(r"Stilling:\s*([^.]+?\.)", text)
                title = title_match.group(1).rstrip(".") if title_match else text

                if title:
                    links.append({"text": title, "url": full_url})

                if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                    clean_c = normalize_company_name(company_name)
                    clean_u = normalize_job_url(full_url)
                    clean_t = title.strip().lower()
                    job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=title,
                        company=company_name,
                        url=full_url,
                        source="Signatur"
                    ))

            structural_hash = hashlib.md5("|".join(sorted(seen_links)).encode()).hexdigest()
            jobs.append({
                "type": "hash",
                "company": company_name,
                "url": base_url,
                "hash": str(structural_hash),
                "links": links,
                "llm_verified": True
            })
            if any(j.get("type") != "hash" for j in jobs):
                logger.info(f"Signatur direct scraper found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
            return jobs
    except Exception as e:
        logger.debug(f"try_signatur_api error for {company_name}: {e}")
    return None


async def try_talentsoft_api(company_name: str, base_url: str) -> Optional[list[dict]]:
    """Fast, direct HTTP extraction for TalentSoft-hosted career sites (e.g. JN Data)."""
    if "talent-soft.com" not in base_url:
        return None

    client_kwargs: dict[str, Any] = {"timeout": 10.0, "follow_redirects": True}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(base_url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            a_tags = soup.find_all("a", href=lambda h: h and "job-" in h)
            jobs = []
            links = []
            seen_links = set()
            for a in a_tags:
                href = a.get("href", "")
                full_url = urljoin(base_url, href)
                if full_url in seen_links:
                    continue
                seen_links.add(full_url)
                title = a.get_text(" ", strip=True)
                if title:
                    links.append({"text": title, "url": full_url})
                if title and is_valid_job(title, "", company_name, "", bypass_geo=True):
                    clean_c = normalize_company_name(company_name)
                    clean_u = normalize_job_url(full_url)
                    clean_t = title.strip().lower()
                    job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=title,
                        company=company_name,
                        url=full_url,
                        source="TalentSoft"
                    ))

            structural_hash = hashlib.md5("|".join(sorted(seen_links)).encode()).hexdigest()
            jobs.append({
                "type": "hash",
                "company": company_name,
                "url": base_url,
                "hash": str(structural_hash),
                "links": links,
                "llm_verified": True
            })
            if any(j.get("type") != "hash" for j in jobs):
                logger.info(f"TalentSoft direct scraper found {len([j for j in jobs if j.get('type') != 'hash'])} elev jobs for {company_name}")
            return jobs
    except Exception as e:
        logger.debug(f"try_talentsoft_api error for {company_name}: {e}")
    return None


async def scrape_company(context: BrowserContext, company: dict, sem: asyncio.Semaphore) -> list[dict]:
    name = company.get("name")
    url = company.get("url")
    if not name or not url or not url.strip().startswith("http"):
        if name:
            logger.debug(f"Skipping {name}: no valid URL configured (url={url!r})")
        return []

    # Bounded by semaphore to prevent rate-limit flooding across all targets
    async with sem:
        # Fast path: Route directly by known ATS domain to eliminate hundreds of wasted HTTP roundtrips
        url_lower = url.lower()
        if "teamtailor.com" in url_lower or "career.teamtailor" in url_lower:
            candidate_ats = (try_teamtailor_api,)
        elif "emply.com" in url_lower or "emply.net" in url_lower or "au.dk" in url_lower:
            candidate_ats = (try_emply_api,)
        elif "myworkdayjobs.com" in url_lower or "lego" in name.lower():
            candidate_ats = (try_workday_api,)
        elif "portal.signatur.dk" in url_lower:
            candidate_ats = (try_signatur_api,)
        elif "talent-soft.com" in url_lower or "talentsoft" in url_lower:
            candidate_ats = (try_talentsoft_api,)
        else:
            # Custom vanity domain: test Teamtailor first (used by many Danish tech firms), then Emply
            candidate_ats = (try_teamtailor_api, try_emply_api)

        for ats_fn in candidate_ats:
            try:
                res = await ats_fn(name, url)
                if res is not None:
                    company["fail_count"] = 0
                    company["last_success"] = datetime.now(timezone.utc).isoformat()
                    return res
            except Exception as e:
                logger.debug(f"Direct ATS check {ats_fn.__name__} failed for {name}: {e}")

        # Fallback: Headless browser crawling for custom or blocked career portals
        logger.info(f"Crawling {name}: {url}")
        jobs = []
        try:
            found_jobs, body_text, structural_hash, extracted_links = await _scrape_company_with_browser_retry(context, url)
            
            # If LLM API key is present, try LLM extraction as high-precision fallback
            llm_jobs, llm_success = await extract_jobs_with_groq(name, url, body_text)
            if llm_jobs:
                for lj in llm_jobs:
                    clean_c = normalize_company_name(name)
                    clean_u = normalize_job_url(lj["url"])
                    clean_t = lj["title"].strip().lower()
                    job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                    jobs.append(format_job(
                        job_id=job_id,
                        title=lj["title"],
                        company=name,
                        url=lj["url"],
                        source="UniversalCrawler+LLM"
                    ))
            elif found_jobs and not llm_success:
                for fj in found_jobs:
                    fj_title = fj["title"].replace("Mulig stilling: ", "")
                    # Validate through the same filter as other scrapers, bypassing geo check
                    if is_valid_job(fj_title, "", name, "", bypass_geo=True):
                        clean_c = normalize_company_name(name)
                        clean_u = normalize_job_url(fj["url"])
                        clean_t = fj_title.strip().lower()
                        job_id = hashlib.md5(f"{clean_c}_{clean_t}_{clean_u}".encode()).hexdigest()
                        jobs.append(format_job(
                            job_id=job_id,
                            title=fj["title"],
                            company=name,
                            url=fj["url"],
                            source="UniversalCrawler"
                        ))
            elif "datatekniker" in body_text.lower() and not llm_success:
                clean_c = normalize_company_name(name)
                clean_u = normalize_job_url(url)
                job_id = hashlib.md5(f"custom_{clean_c}_mulig_stilling_{clean_u}".encode()).hexdigest()
                jobs.append(format_job(
                    job_id=job_id,
                    title="Mulig IT-stilling fundet i teksten på siden!",
                    company=name,
                    url=url,
                    source="UniversalCrawler"
                ))

            # BUG-4 FIX: ALWAYS emit structural hash object for state tracking
            jobs.append({
                "type": "hash",
                "company": name,
                "url": url,
                "hash": str(structural_hash),
                "links": extracted_links,
                "llm_verified": llm_success
            })
            company["fail_count"] = 0
            company["last_success"] = datetime.now(timezone.utc).isoformat()
        except Exception as e:
            logger.error(f"Failed to crawl {name} ({url}): {e}")
            company["fail_count"] = company.get("fail_count", 0) + 1
            
        return jobs


async def scrape_custom_companies(context: BrowserContext, dynamic_companies: Optional[list[dict]] = None) -> list[dict]:
    # Fail fast if target_companies.json is missing or corrupted
    target_path = getattr(config, "TARGET_COMPANIES_PATH", "target_companies.json")
    with open(target_path, "r", encoding="utf-8") as f:
        companies = json.load(f)

    if dynamic_companies:
        # Avoid duplicates by name
        existing_names = {c.get("name", "").lower() for c in companies}
        for dc in dynamic_companies:
            if dc.get("name", "").lower() not in existing_names:
                companies.append(dc)

    if not companies:
        return []

    logger.info(f"Crawling {len(companies)} custom companies in parallel...")
    
    sem = asyncio.Semaphore(3)
    tasks = [scrape_company(context, company, sem) for company in companies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_jobs = []
    for idx, res in enumerate(results):
        company_info = companies[idx] if idx < len(companies) else {}
        comp_name = company_info.get("name", f"Company #{idx}")
        comp_url = company_info.get("url", "unknown URL")
        if isinstance(res, Exception):
            logger.error(f"Scraper failed for company '{comp_name}' ({comp_url}): {res}", exc_info=True)
            company_info["fail_count"] = company_info.get("fail_count", 0) + 1
        elif isinstance(res, list):
            all_jobs.extend(res)
        
    return all_jobs
