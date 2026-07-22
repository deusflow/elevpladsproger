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

async def fetch_rss(url: str) -> list[dict]:
    """Fetch and parse RSS feed into a list of articles."""
    articles = []
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                root = ET.fromstring(resp.text)
                for item in root.findall(".//item"):
                    title = item.findtext("title", "")
                    link = item.findtext("link", "")
                    description = item.findtext("description", "")
                    # Clean up HTML in description (basic cleanup)
                    import re
                    if description:
                        description = re.sub(r'<[^>]+>', ' ', description)
                        description = re.sub(r'\s+', ' ', description).strip()
                    
                    if title and link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "description": description or ""
                        })
    except Exception as e:
        logger.error(f"Failed to fetch RSS from {url}: {e}")
    return articles

async def ask_groq_news(articles: list[dict], target_companies: list[str]) -> dict:
    """
    Pass articles to Groq LLM to check for layoffs/restructuring
    and to generate a Russian digest.
    """
    if not config.GROQ_API_KEY or not articles:
        return {"restructuring_companies": [], "digest_ru": ""}

    # Limit to top 15 latest articles across both feeds, with 800-char descriptions for rich context
    articles_snippet = ""
    for idx, art in enumerate(articles[:15]):
        desc = art['description'][:800] + "..." if len(art['description']) > 800 else art['description']
        articles_snippet += f"[{idx+1}] Title: {art['title']}\nSummary: {desc}\nLink: {art['link']}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""
    You are an expert IT tech journalist and blogger for a popular Telegram channel.
    Below are the latest Danish IT news articles.

    Task 1 (Layoffs/Restructuring):
    Check if any of the following specific companies are mentioned in the news regarding layoffs (fyringer), restructuring, or mass firings:
    Companies: {companies_str}

    Task 2 (Engaging Russian News Post):
    1. Select the single MOST interesting or impactfull IT news article from the provided list.
    2. Write a lively, engaging, well-structured Telegram post in Russian ("живая, увлекательная подача").
    3. Add necessary context, background, or real-world implications so the reader understands WHY this matters.
    
    STRICT Rules for the Russian post:
    - NEVER use robotic boilerplate AI templates or phrases like "Для IT-специалистов это означает...", "Это значит, что нужно быть осведомленным", or "Безопасность должна быть приоритетом".
    - Write naturally, like a human tech editor explaining news to developers and tech enthusiasts.
    - Use clear structure: an engaging headline with an emoji, 2-3 readable paragraphs explaining the news + background context, followed by a bulleted breakdown of practical takeaways or key threats if applicable.
    - End with a clean link line: 🔗 Оригинал: [link]
    - Format strictly for Telegram using standard Markdown.

    Articles:
    {articles_snippet}

    Return a JSON object EXACTLY like this:
    {{
        "restructuring_companies": ["list", "of", "strings"],
        "digest_ru": "Your engaging Russian news post here..."
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
    """Fetch news, analyze with Groq, and return restructuring companies and digest if new articles found."""
    seen_news = state.get("seen_news", [])
    
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
    for source, url in RSS_FEEDS.items():
        articles = await fetch_rss(url)
        all_articles.extend(articles)

    # Filter out seen articles based on link
    new_articles = [art for art in all_articles if art["link"] not in seen_news]
    
    if not new_articles:
        logger.info("No new news articles to process.")
        return {"restructuring_companies": [], "digest_ru": "", "new_links": []}

    logger.info(f"Found {len(new_articles)} new articles. Sending to Groq...")
    
    analysis = await ask_groq_news(new_articles[:15], target_company_names)
    
    digest_ru = analysis.get("digest_ru", "").strip()
    
    # Only mark these links as seen if Groq successfully generated a digest.
    # Otherwise, we might skip them next time even if Groq failed due to rate limits.
    processed_links = [art["link"] for art in new_articles[:15]] if digest_ru else []
    
    return {
        "restructuring_companies": analysis.get("restructuring_companies", []),
        "digest_ru": digest_ru,
        "new_links": processed_links
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
