import httpx
import xml.etree.ElementTree as ET
import logging
import json
import asyncio
from typing import Any
from datetime import datetime
import config
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
logger = logging.getLogger("elevplads_scraper")

import feedparser
import re
import time

DANISH_STOPWORDS = {
    "i", "af", "på", "med", "for", "at", "en", "et", "den", "det", "de", "til", "fra", "om",
    "er", "som", "vil", "har", "ikke", "der", "sig", "kan", "var", "også", "men", "da", "nu",
    "ud", "over", "under", "efter", "ny", "nyt", "nye", "mod", "mere", "mange", "flere"
}

def clean_tokens(s: str) -> set[str]:
    words = re.findall(r'\w+', s.lower())
    return {w for w in words if w not in DANISH_STOPWORDS and len(w) > 2}

def jaccard_similarity(s1: str, s2: str) -> float:
    set1 = clean_tokens(s1)
    set2 = clean_tokens(s2)
    if not set1 or not set2:
        return 0.0
    
    intersection = set1.intersection(set2)
    union = set1.union(set2)
    score = len(intersection) / len(union) if union else 0.0

    # Key entity matching for brands/products (e.g. OpenAI, ChatGPT, Crowdstrike, etc.)
    key_brands = {"openai", "chatgpt", "google", "microsoft", "apple", "nvidia", "crowdstrike", "aub", "eud", "eux"}
    brands1 = set1.intersection(key_brands)
    brands2 = set2.intersection(key_brands)
    
    if brands1 and brands2 and brands1 == brands2:
        # Same major brand/topic: check if any remaining tokens match stem
        rest1 = set1 - key_brands
        rest2 = set2 - key_brands
        for t1 in rest1:
            for t2 in rest2:
                if t1 in t2 or t2 in t1 or (len(t1) >= 4 and len(t2) >= 4 and t1[:4] == t2[:4]):
                    return 0.75 # High similarity match
                    
    return score

async def fetch_rss(url: str) -> tuple[list[dict], bool]:
    """Fetch and parse RSS/Atom feed into a list of articles using feedparser and httpx. Returns (articles, success_flag)."""
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
                    published = getattr(entry, "published_parsed", None)
                    timestamp = time.mktime(published) if published else 0
                    
                    if description:
                        description = re.sub(r'<[^>]+>', ' ', description)
                        description = re.sub(r'\s+', ' ', description).strip()
                    
                    if title and link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "description": description or "",
                            "timestamp": timestamp
                        })
                return articles, True
            else:
                logger.warning(f"Failed to fetch RSS from {url}: HTTP {resp.status_code}")
                return [], False
    except Exception as e:
        logger.error(f"Failed to fetch RSS from {url}: {e}")
        return [], False

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

async def autograde_digest(digest_ru: str, snippets: str) -> bool:
    """Advisory check for hallucinations. Logs warnings without blocking valid generation."""
    if not config.GEMINI_API_KEY:
        return True
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={config.GEMINI_API_KEY}"
    prompt = f"Source text:\n{snippets}\n\nGenerated text:\n{digest_ru}\n\nDoes the generated text invent fake companies, fake URLs, or completely fabricated facts? Reply 'FAIL' only if severely hallucinated, otherwise reply 'OK'."
    payload: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                res = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                if "FAIL" in res.upper():
                    logger.warning(f"Autograder advisory flag: {res}")
    except Exception as e:
        logger.warning(f"Autograder advisory check error: {e}")
    return True

def validate_format(digest_ru: str) -> bool:
    """Validate that digest_ru is non-empty, substantial, and contains basic Telegram links/formatting."""
    if not digest_ru or len(digest_ru) < 80:
        logger.warning("Validation failed: digest too short or empty")
        return False
    # Check for basic link or section marker
    if "http" not in digest_ru and "🔗" not in digest_ru:
        logger.warning("Validation failed: missing original article link")
        return False
    return True

def build_quality_fallback_digest(batch: list[dict], used_term: str) -> str:
    """Build a beautiful, full-structure Telegram post fallback if all LLMs are unreachable."""
    if not batch:
        return ""
    main_art = batch[0]
    title = main_art.get("title", "Главные новости IT").strip()
    link = main_art.get("link", "").strip()
    desc = main_art.get("description", "").strip()
    if len(desc) > 300:
        desc = desc[:297] + "..."
    if not desc:
        desc = "Ключевые события и технологические изменения в IT-сфере Дании и Европы."
        
    term_name = used_term or "REST API"
    
    fallback = (
        f"📰 *{title}*\n\n"
        f"📌 *Что произошло:*\n"
        f"{desc}\n\n"
        f"⚙️ *Техническая суть:*\n"
        f"Подробный разбор и технические детали доступны в первоисточнике публикации.\n\n"
        f"⚡ *Почему это важно:*\n"
        f"Актуальные изменения рынка и технологий напрямую влияют на работу разработчиков и IT-специалистов.\n\n"
        f"🔗 [Читать первоисточник]({link})\n\n"
        f"▫️ ▫️ ▫️\n\n"
        f"💡 *IT-Термин недели: {term_name}*\n\n"
        f"Архитектурный стиль для создания масштабируемых веб-сервисов через HTTP.\n"
        f"• Использует стандартные методы: GET, POST, PUT, DELETE.\n"
        f"• Основан на передаче состояния ресурсов без сохранения сессии."
    )
    return fallback

async def ask_llm_news(articles: list[dict], target_companies: list[str], used_terms: list[str], seen_news: list[dict] = []) -> dict:
    """
    Pass articles to LLM to check for layoffs/restructuring
    and to generate a single Russian digest post with an educational tech fact.
    """
    if (not config.GEMINI_API_KEY and not config.GROQ_API_KEY) or not articles:
        return {"restructuring_companies": [], "digest_ru": "", "used_term": ""}

    # Select an unused tech term
    available_terms = [t for t in config.TECH_TERMS_POOL if t not in used_terms]
    if not available_terms:
        available_terms = config.TECH_TERMS_POOL
    
    import random
    selected_term = random.choice(available_terms)

    # Prepare recent covered topics from seen_news for deduplication & update context
    recent_seen_titles = [item.get("title", "") for item in reversed(seen_news[-20:]) if item.get("title")]
    recent_topics_str = "\n".join([f"- {t}" for t in recent_seen_titles[:15]]) if recent_seen_titles else "None"

    # Context string (articles list)
    articles_snippet = ""
    for idx, art in enumerate(articles):
        desc = art['description'][:800] + "..." if len(art['description']) > 800 else art['description']
        articles_snippet += f"[{idx+1}] Title: {art['title']}\nSummary: {desc}\nLink: {art['link']}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""
    You are a senior IT editor for a top Telegram tech channel read on mobile phones.
    Below are the latest Danish IT news articles.

    Task 1 (Layoffs/Restructuring):
    Check if any of the following specific companies are mentioned in the news regarding layoffs (fyringer), restructuring, or mass firings:
    Companies: {companies_str}

    Task 2 (Single High-Substance Russian Tech Digest Post):
    1. Check the list of RECENTLY PUBLISHED TOPICS in our channel below:
       [Recently Published Topics]:
       {recent_topics_str}

    2. Select the single MOST interesting, technical, or impactful news article from the articles list below.
       CRITICAL TOPIC DEDUPLICATION & UPDATE RULES:
       - DO NOT SELECT an article if it is about the EXACT SAME event/topic already listed in [Recently Published Topics] with no new information! Pick a different, fresh news story instead.
       - IF an article is a genuine NEW DEVELOPMENT or UPDATE to a story in [Recently Published Topics], you MAY select it, but you MUST prefix the headline with:
         "🔄 *Дополнение к вчерашней новости:* [Catchy Headline]" (or "🔄 *Дополнение к новости:* [Catchy Headline]").
       - EXTREME PRIORITY: If an article is about IT Education in Denmark (EUD, EUX, SU, IT-supporter, Datatekniker, admissions), or IT Apprenticeship Laws (elevplads rules, AUB subsidies, overenskomst, elevløn, unions), you MUST prioritize it over general tech news!
       - Otherwise, prioritize topics with a 75% focus on developers (Architecture, Code, DevOps, Cybersecurity) and 25% on the tech scene.

    3. Write a clear, engaging, and SUBSTANTIAL Telegram post in Russian.
    4. At the end, append a SHORT, COMPACT Educational Tech Fact about the term: "{selected_term}"

    CRITICAL TELEGRAM MOBILE FORMATTING RULES:
    - NO LEADING SPACES OR TABS! Every line must start at column 0.
    - Exactly ONE blank line (`\\n\\n`) between sections. Never output multiple empty lines.
    - NO Markdown headers (`#` or `##`)! Use standard Telegram Markdown (v1): *bold*, _italic_, `code`, [link text](url).

    CRITICAL LINGUISTIC RULES FOR AI:
    - DO NOT TRANSLATE EMOJIS! Always output the EXACT emojis from the template (📌, ⚙️, ⚡, 🔗, 💡, 🔄).
    - Headline Emoji: Use 🎓 for Education/Study news, ⚖️ for Laws/Unions/Salaries, 🔄 for updates, and 📰 for general IT/Tech news.
    - The separator line MUST be EXACTLY the three unicode squares `▫️ ▫️ ▫️`.
    - Keep all bold asterisks (*).

    EXACT TELEGRAM TEMPLATE TO FOLLOW (copy the emojis and formatting EXACTLY):
    ```
    [Headline Emoji: 🎓, ⚖️, 🔄, or 📰] *[Catchy, Specific Headline in Russian]*

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

    # 1. Try Gemini API first if key is available
    if config.GEMINI_API_KEY:
        gemini_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-3.5-flash"]
        for g_model in gemini_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={config.GEMINI_API_KEY}"
            payload: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.3
                }
            }
            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=1.5, min=2, max=10),
                    reraise=True
                ):
                    with attempt:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
                            resp = await client.post(url, json=payload)
                            
                            if resp.status_code in [429, 500, 502, 503, 504]:
                                logger.warning(f"Gemini API transient error {resp.status_code} on {g_model}, retrying...")
                                resp.raise_for_status()
                            elif resp.status_code != 200:
                                logger.warning(f"Gemini API error with model {g_model} ({resp.status_code}): {resp.text}")
                                break
                                
                            res_json = resp.json()
                            text_content = res_json["candidates"][0]["content"]["parts"][0]["text"]
                            parsed = extract_json_payload(text_content)
                            digest_ru = parsed.get("digest_ru", "").strip()
                            
                            if not validate_format(digest_ru):
                                raise Exception(f"Format validation failed for {g_model}")
                                
                            await autograde_digest(digest_ru, articles_snippet)
                                
                            logger.info(f"Successfully generated and validated digest via Gemini API model ({g_model})")
                            return parsed
            except Exception as e:
                logger.warning(f"Gemini API exception with model {g_model}: {e}")

    # 2. Fallback to Groq API if Gemini is unavailable or fails
    if config.GROQ_API_KEY:
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
                    {"role": "system", "content": "You are a professional IT editor and JSON writer. Write engaging, beautifully formatted Russian tech news digests."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.4,
                "max_tokens": 2048
            }

            try:
                async for attempt in AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=1.5, min=2, max=10),
                    reraise=True
                ):
                    with attempt:
                        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
                            resp = await client.post(url, headers=headers, json=payload)
                            
                            if resp.status_code in [429, 500, 502, 503, 504]:
                                logger.warning(f"Groq API transient error {resp.status_code} on {model}, retrying...")
                                resp.raise_for_status()
                            elif resp.status_code != 200:
                                logger.warning(f"Groq API error with model {model} ({resp.status_code}): {resp.text}")
                                break 

                            content = resp.json()["choices"][0]["message"]["content"]
                            parsed = extract_json_payload(content)
                            digest_ru = parsed.get("digest_ru", "").strip()
                            
                            if not validate_format(digest_ru):
                                raise Exception(f"Format validation failed for {model}")
                                
                            await autograde_digest(digest_ru, articles_snippet)
                                
                            logger.info(f"Successfully generated and validated digest via Groq fallback ({model})")
                            return parsed
            except Exception as e:
                logger.error(f"Groq API exception during news analysis with model {model}: {e}")

    return {"restructuring_companies": [], "digest_ru": ""}

async def process_news(state: dict, force_post: bool = False) -> dict:
    """Fetch news, analyze with LLM, and return restructuring companies, digest, and used term if new articles found."""
    raw_seen = state.get("seen_news", [])
    used_terms = state.get("used_terms", [])
    
    current_time = datetime.now().timestamp()
    seen_news: list[dict[str, Any]] = []
    
    # Normalize legacy string-based seen_news and enforce 10-day retention
    for item in raw_seen:
        if isinstance(item, str):
            # Legacy string
            seen_news.append({"link": item, "title": "", "timestamp": current_time})
        elif isinstance(item, dict):
            item_time = item.get("timestamp", 0)
            if current_time - item_time <= 864000: # 10 days in seconds
                seen_news.append(item)
    
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

    all_articles: list[dict[str, Any]] = []
    feed_failures = state.get("feed_failures", {})

    for source, url in config.RSS_FEEDS.items():
        articles, success = await fetch_rss(url)
        if not success:
            feed_failures[source] = feed_failures.get(source, 0) + 1
            if feed_failures[source] >= 3:
                logger.error(f"Feed {source} has failed {feed_failures[source]} times consecutively.")
        else:
            feed_failures[source] = 0

        # Semantic Deduplication across feeds
        for art in articles:
            is_dupe = False
            for existing in all_articles:
                if jaccard_similarity(art["title"], existing["title"]) > 0.6:
                    is_dupe = True
                    break
            if not is_dupe:
                all_articles.append(art)
                
    state["feed_failures"] = feed_failures

    # Sort all articles by timestamp descending (newest first)
    all_articles.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    # Cold start logic: if seen_news is completely empty and this is not a force_post,
    # we just seed the seen_news with all current articles to prevent a massive spam wave on first run.
    if len(seen_news) == 0 and len(all_articles) > 0 and not force_post:
        logger.info("Cold start detected. Seeding seen_news with current articles and skipping LLM processing.")
        for art in all_articles:
            seen_news.append({"link": art["link"], "title": art["title"], "timestamp": art.get("timestamp", current_time)})
        return {
            "restructuring_companies": [], 
            "digests_ru": [], 
            "seen_news": seen_news,
            "new_used_terms": []
        }

    # Filter out seen articles based on link unless force_post is True
    if force_post:
        logger.info("force_post is True, skipping seen_news check.")
        new_articles = all_articles
    else:
        new_articles = []
        for art in all_articles:
            is_dupe = False
            for seen in seen_news:
                if seen["link"] == art["link"]:
                    is_dupe = True
                    break
                if seen["title"] and jaccard_similarity(art["title"], seen["title"]) > 0.6:
                    is_dupe = True
                    break
            
            if not is_dupe:
                new_articles.append(art)
    
    if not new_articles:
        logger.info("No new news articles to process.")
        return {"restructuring_companies": [], "digests_ru": [], "new_links": [], "new_used_terms": []}

    # Limit processing candidate set to top 12 fresh articles for 1 single digest post per run
    articles_to_process = new_articles[:12]
    logger.info(f"Found {len(new_articles)} new articles. Generating 1 single digest post from top {len(articles_to_process)} articles...")

    analysis = await ask_llm_news(articles_to_process, target_company_names, used_terms, seen_news=seen_news)
    digest_ru = analysis.get("digest_ru", "").strip()
    
    if not digest_ru:
        logger.warning("LLM generation failed for all models. Using high-quality full structure fallback digest.")
        fallback_term = (set(config.TECH_TERMS_POOL) - set(used_terms)).pop() if (set(config.TECH_TERMS_POOL) - set(used_terms)) else "REST API"
        digest_ru = build_quality_fallback_digest(articles_to_process, fallback_term)
        analysis["digest_ru"] = digest_ru
        analysis["used_term"] = fallback_term
        
    digest_ru = analysis.get("digest_ru", "").strip()
    new_used_term = analysis.get("used_term", "").strip()
    
    digests_ru = []
    processed_links = []
    new_used_terms = []
    restructuring_comps = []

    if digest_ru:
        digests_ru.append(digest_ru)
        processed_links.extend([art["link"] for art in articles_to_process])
        if new_used_term:
            new_used_terms.append(new_used_term)
            used_terms.append(new_used_term)
        restructuring_comps.extend(analysis.get("restructuring_companies", []))

    # Any new articles that were NOT processed should still be marked as seen so they don't clog up the backlog
    if not force_post:
        for art in new_articles[21:]:
            seen_news.append({"link": art["link"], "title": art["title"], "timestamp": art.get("timestamp", current_time)})

    # Also append processed links
    for art in articles_to_process:
        seen_news.append({"link": art["link"], "title": art["title"], "timestamp": art.get("timestamp", current_time)})

    # Dedup the seen_news itself (just in case) based on link
    final_seen = []
    seen_links = set()
    for s in seen_news:
        if s["link"] not in seen_links:
            seen_links.add(s["link"])
            final_seen.append(s)

    return {
        "restructuring_companies": list(set(restructuring_comps)),
        "digests_ru": digests_ru,
        "seen_news": final_seen,
        "new_used_terms": new_used_terms
    }

if __name__ == "__main__":
    # Local quick test
    async def test():
        import config
        from dotenv import load_dotenv
        import os
        load_dotenv()
        config.GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        config.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        res = await process_news({"seen_news": []})
        print(json.dumps(res, indent=2, ensure_ascii=False))
    
    asyncio.run(test())
