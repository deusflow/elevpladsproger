import json
import logging
import asyncio
import os
import re
import hashlib
import httpx
from patchright.async_api import BrowserContext, Page
import config
from scrapers import format_job, is_valid_job
from tenacity import retry, stop_after_attempt, wait_fixed
from playwright_stealth import stealth_async

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
    except Exception:
        pass
        
    for child in frame.child_frames:
        await extract_links_from_frame(child, base_url, found_jobs)

async def extract_jobs_with_groq(company_name: str, page_url: str, page_text: str) -> tuple[list[dict], bool]:
    if not config.GROQ_API_KEY:
        return [], False
        
    truncated_text = page_text[:8000]
    
    prompt = f"""You are an IT job scraper for Denmark (Midtjylland region).
Analyze the following career page text for '{company_name}' ({page_url}).
Identify any IT apprenticeship, IT trainee, IT elevplads, Datatekniker (programmering or cybersecurity), or Software developer elev jobs.

CRUCIAL: You must also look for "hidden" or unsolicited (uopfordret ansøgning) apprenticeship announcements. If a paragraph mentions sending an unsolicited CV or email for an IT-elev or datatekniker role, treat it as a valid job opening with the title "Uopfordret ansøgning: IT-Elev".

IMPORTANT Rules:
- Exclude IT supporter, infrastructure, helpdesk, or non-IT jobs.
- Only return jobs that are IT elev / datatekniker / software development / cybersecurity (including unsolicited/hidden ones).

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
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a precise JSON job extractor."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                result = json.loads(content)
                raw_jobs = result.get("jobs", [])
                extracted = []
                for j in raw_jobs:
                    title = j.get("title", "").strip()
                    job_url = j.get("url", "").strip() or page_url
                    if title and is_valid_job(title, "", company_name, ""):
                        extracted.append({
                            "title": title,
                            "url": job_url
                        })
                if extracted:
                    logger.info(f"Groq LLM extracted {len(extracted)} IT elev jobs for {company_name}")
                return extracted, True
            else:
                logger.warning(f"Groq API error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Error invoking Groq LLM for {company_name}: {e}")
        
    return [], False

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
async def _do_scrape_company(page: Page, url: str):
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000) # Give extra time for JS/Iframes to render
    
    found_jobs = []
    await extract_links_from_frame(page.main_frame, url, found_jobs)
            
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
    
    return found_jobs, body_text, structural_hash


async def scrape_company(context: BrowserContext, company: dict, sem: asyncio.Semaphore) -> list[dict]:
    name = company.get("name")
    url = company.get("url")
    if not name or not url:
        return []
        
    async with sem:
        logger.info(f"Crawling {name}: {url}")
        page = await context.new_page()
        await stealth_async(page)
        jobs = []
        try:
            found_jobs, body_text, structural_hash = await _do_scrape_company(page, url)
            
            # If LLM API key is present, try LLM extraction as high-precision fallback
            llm_jobs, llm_success = await extract_jobs_with_groq(name, url, body_text)
            if llm_jobs:
                for lj in llm_jobs:
                    job_id = hashlib.md5(f"{name}_{lj['title']}_{lj['url']}".encode()).hexdigest()
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
                        job_id = hashlib.md5(f"{name}_{fj_title}_{fj['url']}".encode()).hexdigest()
                        jobs.append(format_job(
                            job_id=job_id,
                            title=fj["title"],
                            company=name,
                            url=fj["url"],
                            source="UniversalCrawler"
                        ))
            elif "datatekniker" in body_text.lower() and not llm_success:
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
                    "hash": str(structural_hash),
                    "llm_verified": llm_success
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

async def scrape_custom_companies(context: BrowserContext, dynamic_companies: list[dict] = None) -> list[dict]:
    jobs = []
    try:
        with open("target_companies.json", "r", encoding="utf-8") as f:
            companies = json.load(f)
    except Exception as e:
        logger.error(f"Could not load target_companies.json: {e}")
        companies = []

    if dynamic_companies:
        # Avoid duplicates by name
        existing_names = {c.get("name", "").lower() for c in companies}
        for dc in dynamic_companies:
            if dc.get("name", "").lower() not in existing_names:
                companies.append(dc)

    if not companies:
        return jobs

    logger.info(f"Crawling {len(companies)} custom companies in parallel...")
    
    sem = asyncio.Semaphore(3)
    tasks = [scrape_company(context, company, sem) for company in companies]
    results = await asyncio.gather(*tasks)
    
    for sublist in results:
        jobs.extend(sublist)
        
    return jobs

