import httpx
import json
import logging
import re
import config
from typing import Any

logger = logging.getLogger("elevplads_scraper")

from utils import extract_json_payload

async def fetch_job_text(url: str) -> str:
    """Fetch job URL and extract text using regex, skipping JS/CSS."""
    try:
        client_kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
        if config.PROXY_URL:
            client_kwargs["proxy"] = config.PROXY_URL
            
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html = resp.text
                
                # Remove scripts, styles, head, svgs
                html = re.sub(r'<(script|style|head|svg|nav|footer)[^>]*>.*?</\1>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
                # Remove HTML tags
                text = re.sub(r'<[^>]+>', ' ', html)
                # Normalize whitespace
                text = re.sub(r'\s+', ' ', text).strip()
                
                return text[:8000]
    except Exception as e:
        logger.warning(f"Failed to fetch {url} for scoring: {e}")
    return ""

async def get_match_score(title: str, company: str, text: str) -> dict:
    """Ask Gemini LLM (with Groq fallback) to score the job match based on text."""
    if not config.GEMINI_API_KEY and not config.GROQ_API_KEY:
        return {}
        
    prompt = f"""
    You are an expert IT job match analyzer for Denmark.
    Evaluate this job posting for a Danish IT apprenticeship (Elevplads / lærling) or trainee role.

    PRIMARY GOAL: the candidate is a Datatekniker (Data- og kommunikationsuddannelsen) apprentice.
    He wants Datatekniker roles with these priorities:
      1. Datatekniker med speciale i programmering / software development  (HIGHEST priority)
      2. Datatekniker med speciale i cybersikkerhed / IT-security
      3. Datatekniker med speciale i infrastruktur / drift / netværk, and generic IT-elev roles
    EXPLICITLY EXCLUDED: It-supporter, helpdesk, servicedesk, user-support roles (score 0),
    and any non-IT role (score 0).

    Candidate Profile:
    {config.USER_PROFILE}
    
    Cover Letter Template Guide (Use this as the structure and adapt it dynamically for the company):
    {config.COVER_LETTER_TEMPLATE}
    
    Target keywords: {", ".join(config.TARGET_KEYWORDS)}
    Exclude keywords: {", ".join(config.EXCLUDE_KEYWORDS)}
    
    Job Title: {title}
    Company: {company}
    
    Job Description Snippet:
    {text}
    
    Return a JSON object EXACTLY like this:
    {{
        "score": 95,
        "city": "Aarhus",
        "reason": "Perfekt match for IT-elev med fokus på programmering og cybersikkerhed.",
        "cover_letter_draft": "Kære {company}, ..."
    }}
    
    Rules:
    - "score" must be an integer from 0 to 100 representing how perfectly it matches the Candidate Profile:
        * 90-100: Datatekniker eller IT-elev med fokus på programmering, softwareudvikling eller kodning.
        * 75-89: Datatekniker med speciale i cybersikkerhed / IT-sikkerhed.
        * 55-74: Datatekniker med speciale i infrastruktur, drift eller netværk, samt generiske IT-elev-stillinger.
        * 0: It-supporter, helpdesk, servicedesk, brugerstøtte, eller ikke-IT-stillinger (fx butik, lager, marketing).
    - "city" must be the city extracted from the text (or "Ukendt" if not found).
    - "reason" must be ONE short Danish sentence summarizing why it's a good/bad match.
    - "cover_letter_draft": If score > 85, write a professional, compelling draft cover letter (Ansøgning) in Danish based on the Candidate Profile and Job Description. If score <= 85, return an empty string "". DO NOT output markdown blocks around the JSON.
    """
    
    # 1. Try Google Gemini models
    if config.GEMINI_API_KEY:
        gemini_models = ["gemini-2.5-flash-lite", "gemini-2.0-flash"]
        for g_model in gemini_models:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={config.GEMINI_API_KEY}"
            gemini_payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json"
                }
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(gemini_url, json=gemini_payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["candidates"][0]["content"]["parts"][0]["text"]
                        parsed = extract_json_payload(content)
                        if isinstance(parsed, dict) and "score" in parsed:
                            return parsed
                    elif resp.status_code in [429, 503]:
                        logger.warning(f"Gemini API status {resp.status_code} on {g_model}, switching immediately to next model...")
                        continue
                    else:
                        logger.warning(f"Gemini API scoring error {resp.status_code} on {g_model}: {resp.text}")
                        continue
            except Exception as e:
                logger.warning(f"Gemini API exception during scoring ({g_model}): {e}, switching to next model...")
                continue
            
    # 2. Fallback to Groq models
    if config.GROQ_API_KEY:
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        groq_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
        for model_id in groq_models:
            payload = {
                "model": model_id,
                "messages": [
                    {"role": "system", "content": "You are a JSON-only job evaluator. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }
            
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(groq_url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        parsed = extract_json_payload(content)
                        if isinstance(parsed, dict) and "score" in parsed:
                            return parsed
                    elif resp.status_code in [429, 503]:
                        logger.warning(f"Groq API status {resp.status_code} on {model_id}, switching immediately to next model...")
                        continue
                    else:
                        logger.warning(f"Groq API scoring error {resp.status_code} on {model_id}: {resp.text}")
                        continue
            except Exception as e:
                logger.warning(f"Groq API exception during scoring ({model_id}): {e}, switching to next model...")
                continue
        
    return {}
    
async def enrich_jobs_with_ai(new_jobs: list[dict]):
    """Fetch text and score each new job asynchronously with isolated error handling."""
    if not new_jobs or (not config.GEMINI_API_KEY and not config.GROQ_API_KEY):
        return
        
    logger.info(f"Enriching {len(new_jobs)} new jobs with AI match score...")
    
    async def process_job(job):
        try:
            text = await fetch_job_text(job["url"])
            score_data = await get_match_score(job["title"], job["company"], text)
            if score_data:
                job["match_score"] = score_data.get("score")
                job["match_city"] = score_data.get("city")
                job["match_reason"] = score_data.get("reason")
                job["cover_letter_draft"] = score_data.get("cover_letter_draft", "")
                logger.info(f"Scored job {job['title']}: {job.get('match_score')}%")
        except Exception as e:
            logger.warning(f"Error enriching job '{job.get('title')}': {e}")
            
    import asyncio
    sem = asyncio.Semaphore(3)
    
    async def process_job_with_sem(job):
        async with sem:
            await process_job(job)
            
    results = await asyncio.gather(*(process_job_with_sem(job) for job in new_jobs), return_exceptions=True)
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            logger.warning(f"Failed to score job #{idx} ({new_jobs[idx].get('title')}): {res}")
