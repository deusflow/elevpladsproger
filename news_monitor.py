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
    You are a world-class IT tech journalist and senior editor for a popular Telegram tech channel read by developers and engineers.
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
    3. At the very end of the post, append an Educational Tech Fact about the term: "{selected_term}"

    CRITICAL STRUCTURE AND VISUAL FORMATTING REQUIREMENTS:
    - ALWAYS insert DOUBLE line breaks (`\n\n`) between EVERY paragraph, subsection, link, and block! Do NOT merge text into wall-of-text blocks.
    - NEVER use Markdown headers (`#` or `##`)! Use standard Telegram Markdown (v1): *bold*, _italic_, `code`, [link text](url).

    EXACT POST STRUCTURE TO FOLLOW:

    📰 *[Catchy, Specific Headline in Russian]*

    📌 *Что произошло:*
    [1-2 clear sentences explaining the exact news event]

    ⚙️ *Техническая суть:*
    [2-3 detailed sentences explaining how the underlying technology works, what replaces the old way, and exact mechanisms]

    ⚡ *Почему это важно:*
    [1-2 sentences explaining practical impact for developers, security, or the tech market]

    🔗 [Читать первоисточник]([original_link])

    ───────────────

    💡 *IT-Термин недели: {selected_term}*

    [Short 2-3 sentence definition explaining the concept simply and clearly without fluff]

    • [Bullet point 1]
    • [Bullet point 2]
    • [Bullet point 3]

    CRITICAL Requirements for the Tech Fact Footer ("{selected_term}"):
    - Length MUST be 400-600 characters total.
    - No generic intros like "Сегодня разберем...". Start directly with the core definition.

    Articles:
    {articles_snippet}

    Return a JSON object EXACTLY like this:
    {{
        "restructuring_companies": ["list", "of", "strings"],
        "digest_ru": "Your complete Telegram post with exact double line breaks and section dividers...",
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
