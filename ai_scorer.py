import httpx
import json
import logging
import re
import config
from typing import Any

logger = logging.getLogger("elevplads_scraper")

def extract_json_payload(text_content: str) -> dict:
    """Extract and parse JSON object from LLM response text, stripping markdown codeblocks if present."""
    text_content = text_content.strip()
    if text_content.startswith("```"):
        lines = text_content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text_content = "\n".join(lines).strip()
    start = text_content.find("{")
    end = text_content.rfind("}")
    if start != -1 and end != -1:
        text_content = text_content[start:end+1]
    return json.loads(text_content, strict=False)

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
    Evaluate this job posting for an IT Apprenticeship (Elevplads) or Trainee role.
    
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
    - "score" must be an integer from 0 to 100 representing how perfectly it matches the Candidate Profile. Give 0 if it's explicitly 'IT-supporter', 'Infrastruktur', or non-IT.
    - "city" must be the city extracted from the text (or "Ukendt" if not found).
    - "reason" must be ONE short Danish sentence summarizing why it's a good/bad match.
    - "cover_letter_draft": If score > 85, write a professional, compelling draft cover letter (Ansøgning) in Danish based on the Candidate Profile and Job Description. If score <= 85, return an empty string "". DO NOT output markdown blocks around the JSON.
    """
    
    # Try Gemini first
    if config.GEMINI_API_KEY:
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={config.GEMINI_API_KEY}"
        gemini_payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(gemini_url, json=gemini_payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["candidates"][0]["content"]["parts"][0]["text"]
                    return extract_json_payload(content)
                else:
                    logger.warning(f"Gemini API scoring error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Gemini API exception during scoring: {e}")
            
    # Fallback to Groq
    if config.GROQ_API_KEY:
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.1-8b-instant",
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
                    return extract_json_payload(content)
                else:
                    logger.warning(f"Groq API scoring error {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Groq API exception during scoring: {e}")
    
    return {}
    
async def enrich_jobs_with_ai(new_jobs: list[dict]):
    """Fetch text and score each new job asynchronously."""
    if not new_jobs or (not config.GEMINI_API_KEY and not config.GROQ_API_KEY):
        return
        
    logger.info(f"Enriching {len(new_jobs)} new jobs with AI match score...")
    
    async def process_job(job):
        text = await fetch_job_text(job["url"])
        score_data = await get_match_score(job["title"], job["company"], text)
        if score_data:
            job["match_score"] = score_data.get("score")
            job["match_city"] = score_data.get("city")
            job["match_reason"] = score_data.get("reason")
            job["cover_letter_draft"] = score_data.get("cover_letter_draft", "")
            logger.info(f"Scored job {job['title']}: {job.get('match_score')}%")
            
    import asyncio
    sem = asyncio.Semaphore(3)
    
    async def process_job_with_sem(job):
        async with sem:
            await process_job(job)
            
    await asyncio.gather(*(process_job_with_sem(job) for job in new_jobs))
