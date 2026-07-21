import httpx
import json
import logging
import re
import config

logger = logging.getLogger("elevplads_scraper")

async def fetch_job_text(url: str) -> str:
    """Fetch job URL and extract text using regex, skipping JS/CSS."""
    try:
        client_kwargs = {"timeout": 15.0, "follow_redirects": True}
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
    """Ask Groq LLM to score the job match based on text."""
    if not config.GROQ_API_KEY:
        return {}
        
    prompt = f"""
    You are an expert IT job match analyzer for Denmark.
    Evaluate this job posting for an IT Apprenticeship (Elevplads) or Trainee role.
    Target profiles: {", ".join(config.TARGET_KEYWORDS)}
    Exclude profiles: {", ".join(config.EXCLUDE_KEYWORDS)}
    
    Job Title: {title}
    Company: {company}
    
    Job Description Snippet:
    {text}
    
    Return a JSON object EXACTLY like this:
    {{
        "score": 95,
        "city": "Aarhus",
        "reason": "Perfekt match for IT-elev med fokus på programmering og cybersikkerhed."
    }}
    
    Rules:
    - "score" must be an integer from 0 to 100 representing how perfectly it matches a Datatekniker / IT-Elev role in Midtjylland. Give 0 if it's explicitly 'IT-supporter', 'Infrastruktur', or non-IT.
    - "city" must be the city extracted from the text (or "Ukendt" if not found).
    - "reason" must be ONE short Danish sentence summarizing why it's a good/bad match.
    """
    
    url = "https://api.groq.com/openai/v1/chat/completions"
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
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            else:
                logger.warning(f"Groq API scoring error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Groq API exception during scoring: {e}")
    
    return {}
    
async def enrich_jobs_with_ai(new_jobs: list[dict]):
    """Fetch text and score each new job asynchronously."""
    if not new_jobs or not config.GROQ_API_KEY:
        return
        
    logger.info(f"Enriching {len(new_jobs)} new jobs with AI match score...")
    
    async def process_job(job):
        text = await fetch_job_text(job["url"])
        score_data = await get_match_score(job["title"], job["company"], text)
        if score_data:
            job["match_score"] = score_data.get("score")
            job["match_city"] = score_data.get("city")
            job["match_reason"] = score_data.get("reason")
            logger.info(f"Scored job {job['title']}: {job.get('match_score')}%")
            
    import asyncio
    await asyncio.gather(*(process_job(job) for job in new_jobs))
