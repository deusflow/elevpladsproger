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

    # Limit to top 20 latest articles across both feeds to save tokens
    articles_snippet = ""
    for idx, art in enumerate(articles[:20]):
        articles_snippet += f"[{idx+1}] Title: {art['title']}\nSummary: {art['description']}\nLink: {art['link']}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""
    You are an expert IT news analyst for a Telegram channel.
    Below are the latest Danish IT news articles.

    Task 1 (Layoffs/Restructuring):
    Check if any of the following specific companies are mentioned in the news regarding layoffs (fyringer), restructuring, or mass firings:
    Companies: {companies_str}

    Task 2 (Russian News Feed):
    Select the most generally relevant IT news from these articles (focus on big tech, local Danish IT market, AI, major layoffs, or anything interesting for IT professionals).
    Write an engaging, free-form news post in Russian for a Telegram channel. Tell a short story or give an interesting summary of what's happening. Add emojis.
    Include the links to the original articles you mention. If there are no relevant news, leave it empty.

    Articles:
    {articles_snippet}

    Return a JSON object EXACTLY like this:
    {{
        "restructuring_companies": ["CompanyName1", "CompanyName2"],
        "digest_ru": "📢 Срочные новости ИТ Дании!\\n\\nСегодня стало известно, что... [Читать далее](link)"
    }}

    Rules:
    - Return valid JSON only.
    - If no companies are restructuring, return an empty list [].
    - Ensure the Russian digest is well-formatted for Telegram (markdown links).
    """

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a JSON-only news analyzer. Return ONLY valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            else:
                logger.warning(f"Groq API news error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Groq API exception during news analysis: {e}")

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
    
    # Analyze the newest unseen articles (cap at 20 so Groq doesn't timeout/overflow context)
    analysis = await ask_groq_news(new_articles[:20], target_company_names)
    
    # Extract links of the newly processed articles to save in state
    processed_links = [art["link"] for art in new_articles[:20]]
    
    return {
        "restructuring_companies": analysis.get("restructuring_companies", []),
        "digest_ru": analysis.get("digest_ru", ""),
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
