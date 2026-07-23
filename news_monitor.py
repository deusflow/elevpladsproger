import httpx
import xml.etree.ElementTree as ET
import logging
import json
import asyncio
from datetime import datetime
import config

logger = logging.getLogger("elevplads_scraper")

RSS_FEEDS = {
    "Version2": "https://www.version2.dk/rss",
    "Computerworld": "https://www.computerworld.dk/rss/all"
}

import feedparser
import re

async def fetch_rss(url: str) -> list[dict]:
    """Fetch and parse RSS/Atom feed into a list of articles using feedparser and httpx."""
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/rdf+xml, application/atom+xml, application/xml, text/xml, */*"
    }
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                feed = feedparser.parse(resp.content)
                for entry in feed.entries:
                    title = getattr(entry, "title", "")
                    link = getattr(entry, "link", "")
                    description = getattr(entry, "description", getattr(entry, "summary", ""))
                    
                    if description:
                        description = re.sub(r'<[^>]+>', ' ', description)
                        description = re.sub(r'\s+', ' ', description).strip()
                    
                    if title and link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "description": description or ""
                        })
            else:
                logger.warning(f"Failed to fetch RSS from {url}: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"Failed to fetch RSS from {url}: {e}")
    return articles

async def ask_groq_news(articles: list[dict], target_companies: list[str], used_terms: list[str]) -> dict:
    """
    Pass articles to Groq LLM to check for layoffs/restructuring
    and to generate a Russian digest with an educational tech fact.
    """
    if not config.GROQ_API_KEY or not articles:
        return {"restructuring_companies": [], "digest_ru": "", "used_term": ""}

    # Select an unused tech term
    available_terms = [t for t in config.TECH_TERMS_POOL if t not in used_terms]
    if not available_terms:
        # If all exhausted, clear history and start over
        available_terms = config.TECH_TERMS_POOL
    
    import random
    selected_term = random.choice(available_terms)

    # Limit to top 15 latest articles across feeds, with 800-char descriptions for rich context
    articles_snippet = ""
    for idx, art in enumerate(articles[:15]):
        desc = art['description'][:800] + "..." if len(art['description']) > 800 else art['description']
        articles_snippet += f"[{idx+1}] Title: {art['title']}\nSummary: {desc}\nLink: {art['link']}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""
    You are a senior IT editor for a top Telegram tech channel read on mobile phones (iPhones / Android).
    Below are the latest Danish IT news articles.

    Task 1 (Layoffs/Restructuring):
    Check if any of the following specific companies are mentioned in the news regarding layoffs (fyringer), restructuring, or mass firings:
    Companies: {companies_str}

    Task 2 (High-Substance Russian Tech Digest Post):
    1. Select the single MOST interesting, technical, or impactful IT news article from the list.
       - Prioritize topics with a 75% focus on developers: Software Architecture, Code, Frameworks, Cloud/DevOps, Cybersecurity, AI tools for devs, Job market/Salaries.
       - 25% focus on broader Tech Scene: Startups, IT policy, major infra.
       - Ignore consumer gadget reviews or non-IT fluff.
    2. Write a clear, engaging, and SUBSTANTIAL Telegram post in Russian.
    3. At the end, append a SHORT, COMPACT Educational Tech Fact about the term: "{selected_term}"

    CRITICAL TELEGRAM MOBILE FORMATTING RULES:
    - NO LEADING SPACES OR TABS! Every line must start at column 0.
    - Exactly ONE blank line (`\\n\\n`) between sections. Never output multiple empty lines.
    - NO Markdown headers (`#` or `##`)! Use standard Telegram Markdown (v1): *bold*, _italic_, `code`, [link text](url).

    CRITICAL LINGUISTIC RULES FOR AI:
    - DO NOT TRANSLATE EMOJIS! Always output the EXACT emojis from the template (📰, 📌, ⚙️, ⚡, 🔗, 💡). Never translate them to text like "Свет" or "Точка".
    - The separator line MUST be EXACTLY the three unicode squares `▫️ ▫️ ▫️`. Do NOT write "Точка Точка Точка".
    - Keep all bold asterisks (*).

    CRITICAL CONTENT EXPANSION REQUIREMENTS:
    - EXPAND WITH DOMAIN KNOWLEDGE: RSS snippets are often brief. You MUST use your extensive internal IT domain knowledge to expand on the topic and write real, detailed, high-value technical paragraphs for ⚙️ *Техническая суть:* and ⚡ *Почему это важно:*. 
    - NEVER write generic one-liners. Explain the SPECIFIC tech, protocols, frameworks, or architectural impact!

    EXACT TELEGRAM TEMPLATE TO FOLLOW (copy the emojis and formatting EXACTLY):
    ```
    📰 *[Catchy, Specific Headline in Russian]*

    📌 *Что произошло:*
    [1-2 clear sentences explaining the event]

    ⚙️ *Техническая суть:*
    [2-3 detailed technical sentences explaining the underlying mechanism/architecture/technology]

    ⚡ *Почему это важно:*
    [1-2 informative sentences on practical impact for developers or the IT industry]

    🔗 [Читать первоисточник]([original_link])

    ▫️ ▫️ ▫️

    💡 *IT-Термин недели: {selected_term}*

    [1-2 short sentences defining the term directly and simply without fluff]
    • [Short key point 1 (max 1 line)]
    • [Short key point 2 (max 1 line)]
    ```

    CRITICAL Requirements for the Tech Fact Footer ("{selected_term}"):
    - Keep it ULTRA-CONCISE (200–350 characters total).
    - Maximum 2 bullet points. Each bullet point MUST be 1 short line.

    Articles:
    {articles_snippet}

    Return a JSON object EXACTLY like this:
    {{
        "restructuring_companies": ["list", "of", "strings"],
        "digest_ru": "Your clean, unindented Telegram post following the template EXACTLY...",
        "used_term": "{selected_term}"
    }}

    Rules:
    - Return valid JSON only.
    - If no companies are restructuring, return an empty list [].
    - You MUST ALWAYS pick at least one news article and write digest_ru.
    """

    models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    for model in models_to_try:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a professional IT journalist and JSON writer. Write engaging, non-robotic tech news digests."},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
            "max_tokens": 2048
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    return json.loads(content)
                else:
                    logger.warning(f"Groq API news error with model {model} ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.error(f"Groq API exception during news analysis with model {model}: {e}")

    return {"restructuring_companies": [], "digest_ru": ""}

async def process_news(state: dict) -> dict:
    """Fetch news, analyze with Groq, and return restructuring companies, digest, and used term if new articles found."""
    seen_news = state.get("seen_news", [])
    used_terms = state.get("used_terms", [])
    
    # Collect all target companies
    import json as json_lib
    target_companies = []
    try:
        with open("target_companies.json", "r", encoding="utf-8") as f:
            target_companies = json_lib.load(f)
    except:
        pass
    
    target_company_names = [c["name"] for c in target_companies]
    target_company_names.extend([c["name"] for c in state.get("dynamic_companies", [])])
    target_company_names = list(set(target_company_names)) # dedup

    all_articles = []
    for source, url in config.RSS_FEEDS.items():
        articles = await fetch_rss(url)
        all_articles.extend(articles)

    # Filter out seen articles based on link
    new_articles = [art for art in all_articles if art["link"] not in seen_news]
    
    if not new_articles:
        logger.info("No new news articles to process.")
        return {"restructuring_companies": [], "digest_ru": "", "new_links": [], "new_used_term": ""}

    logger.info(f"Found {len(new_articles)} new articles. Sending to Groq...")
    
    analysis = await ask_groq_news(new_articles[:15], target_company_names, used_terms)
    
    digest_ru = analysis.get("digest_ru", "").strip()
    new_used_term = analysis.get("used_term", "").strip()
    
    # Only mark these links as seen if Groq successfully generated a digest.
    processed_links = [art["link"] for art in new_articles[:15]] if digest_ru else []
    
    return {
        "restructuring_companies": analysis.get("restructuring_companies", []),
        "digest_ru": digest_ru,
        "new_links": processed_links,
        "new_used_term": new_used_term
    }

if __name__ == "__main__":
    # Local quick test
    async def test():
        import config
        from dotenv import load_dotenv
        import os
        load_dotenv()
        config.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        res = await process_news({"seen_news": []})
        print(json.dumps(res, indent=2, ensure_ascii=False))
    
    asyncio.run(test())
