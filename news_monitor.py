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
    "ud", "over", "under", "efter", "ny", "nyt", "nye", "mod", "mere", "mange", "flere",
    "blev", "bliver", "ved", "kun", "når", "andre", "meget", "alle", "denne", "disse",
    "skal", "her", "hvad", "hvordan", "hvorfor", "stor", "stort", "store"
}

# Synonym groups: words that mean the same thing in news context
# If two titles share the same entity AND matching synonym groups, they're about the same event
SYNONYM_GROUPS = [
    {"sandbox", "sandkasse", "isoleret", "kontrolleret", "miljø", "miljøet", "isolation"},
    {"brød", "bryder", "undslap", "undslappet", "undslippe", "omgik", "omgå", "flygtede", "escapede", "broke", "escape", "escaped", "vyrset"},
    {"agent", "model", "modellen", "agenten", "bot", "system", "ai", "kunstig", "intelligens"},
    {"sikkerhed", "sikkerhedstest", "sikkerhedsforanstaltninger", "sikkerhedsforskere", "sikkerheds", "security"},
    {"fyring", "fyringer", "afskedigelse", "afskedigelser", "nedskæringer", "nedskæring", "opsigelse", "opsigelser", "layoff", "layoffs"},
    {"ansætter", "ansættelse", "ansættelser", "rekrutterer", "rekruttering", "hiring"},
    {"hacket", "hacking", "hack", "hackere", "cyberangreb", "angreb", "databrud", "breach", "lækket", "læk"},
    {"lancerer", "lancering", "præsenterer", "præsentation", "annoncerer", "annoncering", "offentliggør", "udgivelse", "release"},
    {"opkøb", "opkøber", "køber", "køb", "acquisition", "overtager", "overtagelse", "fusionerer", "fusion"},
    {"elev", "elevplads", "elevpladser", "lærling", "lærlinge", "læreplads", "lærepladser", "apprentice"},
]

# Key named entities that anchor topic identity
KEY_ENTITIES = {
    "openai", "chatgpt", "gpt", "google", "gemini", "microsoft", "copilot",
    "apple", "nvidia", "crowdstrike", "meta", "amazon", "aws", "tesla",
    "aub", "eud", "eux", "datatekniker", "anthropic", "claude", "deepmind",
    "github", "docker", "kubernetes", "linux", "android", "tiktok",
    "twitter", "threads", "instagram", "whatsapp", "signal", "telegram"
}

def clean_tokens(s: str) -> set[str]:
    words = re.findall(r'\w+', s.lower())
    return {w for w in words if w not in DANISH_STOPWORDS and len(w) > 2}

def get_topic_fingerprint(title: str) -> set[str]:
    """Extract a normalized topic fingerprint from a title.
    Maps synonyms to canonical forms and extracts named entities.
    Two articles about the same event will share the same fingerprint even with different vocabulary."""
    tokens = clean_tokens(title)
    fingerprint: set[str] = set()

    # 1. Add any named entities directly
    for token in tokens:
        if token in KEY_ENTITIES:
            fingerprint.add(token)

    # 2. Map tokens to synonym group IDs
    for i, group in enumerate(SYNONYM_GROUPS):
        for token in tokens:
            if token in group:
                fingerprint.add(f"syn:{i}")
                break

    return fingerprint

def is_topic_duplicate(title1: str, title2: str) -> bool:
    """Check if two titles are about the same topic/event.
    Uses a combination of: entity overlap, synonym group matching, and Jaccard similarity."""
    if not title1 or not title2:
        return False

    # Layer 1: Direct Jaccard on cleaned tokens (catches obvious dupes)
    set1 = clean_tokens(title1)
    set2 = clean_tokens(title2)
    if set1 and set2:
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        jaccard = len(intersection) / len(union)
        if jaccard > 0.5:  # Lowered from 0.6 since we strip stopwords now
            return True

    # Layer 2: Topic fingerprint matching
    fp1 = get_topic_fingerprint(title1)
    fp2 = get_topic_fingerprint(title2)

    if not fp1 or not fp2:
        return False

    # Both must share at least one named entity
    entities1 = {t for t in fp1 if not t.startswith("syn:")}
    entities2 = {t for t in fp2 if not t.startswith("syn:")}
    shared_entities = entities1 & entities2

    if not shared_entities:
        return False

    # If they share an entity AND at least one synonym group, it's the same topic
    syns1 = {t for t in fp1 if t.startswith("syn:")}
    syns2 = {t for t in fp2 if t.startswith("syn:")}
    shared_syns = syns1 & syns2

    if shared_entities and shared_syns:
        return True

    # If they share 2+ entities, likely same topic even without synonym match
    if len(shared_entities) >= 2:
        return True

    return False

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
                feed = await asyncio.to_thread(feedparser.parse, resp.content)
                for entry in feed.entries:
                    title = getattr(entry, "title", "")
                    # Strip any HTML tags from titles (some feeds like debat/rss leak raw HTML)
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    link = getattr(entry, "link", "")
                    description = getattr(entry, "description", getattr(entry, "summary", ""))
                    published = getattr(entry, "published_parsed", None)
                    try:
                        timestamp = time.mktime(published) if published else 0
                    except (OverflowError, ValueError, TypeError):
                        timestamp = 0
                    
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

async def fetch_article_content(url: str) -> tuple[str, bool]:
    """
    Fetches the web page content of an article, strips boilerplate/nav/ads,
    and checks for paywall indicators. Returns (clean_text, is_paywalled).
    """
    if not url or not url.startswith("http"):
        return "", False
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }
        client_kwargs: dict[str, Any] = {"timeout": 12.0, "follow_redirects": True}
        if config.PROXY_URL:
            client_kwargs["proxy"] = config.PROXY_URL
            
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                html = resp.text
                # Remove scripts, styles, head, svg, nav, footer, header, aside, form
                html = re.sub(r'<(script|style|head|svg|nav|footer|header|aside|form)[^>]*>.*?</\1>', ' ', html, flags=re.IGNORECASE | re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', html)
                text = re.sub(r'\s+', ' ', text).strip()
                
                # Check for paywall indicators
                text_lower = text.lower()
                paywall_keywords = [
                    "kun for abonnenter", "kræver abonnement", "køb abonnement",
                    "tilmeld dig for at læse", "lås artiklen op", "er forbeholdt abonnenter",
                    "bliv abonnent", "dette indhold er låst", "premium-artikel"
                ]
                is_paywalled = any(pw in text_lower for pw in paywall_keywords)
                
                # Return first 3500 chars of clean substantive text
                return text[:3500], is_paywalled
    except Exception as e:
        logger.debug(f"Could not fetch full article text for {url}: {e}")
    return "", False

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
    """Check for hallucinations, fabricated courses, and ungrounded claims. Returns False if digest is hallucinated."""
    if not config.GEMINI_API_KEY:
        return True
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={config.GEMINI_API_KEY}"
    prompt = f"""Source article text:
{snippets[:4000]}

Generated Russian Telegram post:
{digest_ru}

Fact-Check Task:
Compare the generated Russian text against the source text.
Does the generated text invent fake facts, unmentioned educational courses/modules, non-existent AI/DevOps tools, or invent claims not supported by the source text?
Reply 'FAIL' if the post invents ungrounded facts or distorts the source. Reply 'OK' if the post is factually faithful to the source text."""
    payload: dict[str, Any] = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                res = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                if "FAIL" in res.upper():
                    logger.warning(f"Autograder BLOCKED hallucinated digest: {res}")
                    return False
    except Exception as e:
        logger.warning(f"Autograder check error (allowing digest): {e}")
    return True

def validate_format(digest_ru: str) -> bool:
    """Validate that digest_ru is non-empty, substantial, and contains links."""
    if not digest_ru or len(digest_ru) < 80:
        logger.warning("Validation failed: digest too short or empty")
        return False
    # Check for basic link (HTML <a href> or raw http or emoji link marker)
    if "http" not in digest_ru and "🔗" not in digest_ru and "<a " not in digest_ru:
        logger.warning("Validation failed: missing original article link")
        return False
    return True

def build_quality_fallback_digest(batch: list[dict]) -> str:
    """Build a full-structure Telegram post fallback in HTML if all LLMs are unreachable."""
    if not batch:
        return ""
    import html as _html
    main_art = batch[0]
    title = _html.escape(main_art.get("title", "Главные новости IT").strip())
    link = main_art.get("link", "").strip()
    desc = _html.escape(main_art.get("description", "").strip())
    if len(desc) > 300:
        desc = desc[:297] + "..."
    if not desc:
        desc = "Ключевые события и технологические изменения в IT-сфере Дании и Европы."
        
    fallback = (
        f"📰 <b>{title}</b>\n\n"
        f"{desc}\n\n"
        f"Актуальные изменения рынка и технологий напрямую влияют на работу разработчиков и IT-специалистов. Подробный разбор и технические детали доступны в первоисточнике.\n\n"
        f'🔗 <a href="{link}">Читать полностью</a>\n\n'
        f"💡 <b>Полезно знать:</b> Если внешние сервисы AI временно недоступны, система автоматически публикует этот краткий выпуск, чтобы вы не пропустили важное."
    )
    return fallback

async def ask_llm_news(articles: list[dict], target_companies: list[str], posted_news: list[str]) -> dict:
    """
    Pass articles to LLM to check for layoffs/restructuring
    and to generate a single Russian digest post with strict factual grounding.
    """
    if (not config.GEMINI_API_KEY and not config.GROQ_API_KEY) or not articles:
        return {"restructuring_companies": [], "digest_ru": ""}

    # Split posted_news into headlines and tips for separate dedup
    recent_headlines = [t for t in posted_news if not t.startswith("TIP:")]
    recent_tips = [t.removeprefix("TIP:").strip() for t in posted_news if t.startswith("TIP:")]
    
    recent_topics_str = "\n".join([f"- {t}" for t in recent_headlines[-15:]]) if recent_headlines else "None"
    recent_tips_str = "\n".join([f"- {t}" for t in recent_tips[-10:]]) if recent_tips else "None"

    # Pick a random category for the tip to ensure variety
    import random
    tip_categories = [
        "Полезный инструмент или библиотека для разработчика (например: CLI-утилита, VS Code расширение, npm/pip пакет)",
        "Новая технология или концепция в AI/ML (например: новый подход в fine-tuning, RAG, агентные фреймворки)",
        "Паттерн проектирования или архитектурная концепция (например: CQRS, Event Sourcing, чистая архитектура)",
        "Практический совет по карьере в IT (собеседования, soft skills, рост, менторство)",
        "Малоизвестный исторический факт из мира IT (пасхалки, истории создания технологий, курьёзы)",
        "Полезная техника программирования (например: дебаг-приём, оптимизация, работа с Git)",
    ]
    selected_category = random.choice(tip_categories)

    # Enrich candidate articles with real webpage text in parallel
    async def enrich_article(art: dict) -> dict:
        body, is_paywalled = await fetch_article_content(art.get("link", ""))
        art_copy = dict(art)
        art_copy["body"] = body
        art_copy["is_paywalled"] = is_paywalled
        return art_copy

    logger.info("Fetching full article texts for candidate news...")
    enriched_articles = await asyncio.gather(*[enrich_article(a) for a in articles[:8]])
    for a in articles[8:]:
        art_copy = dict(a)
        art_copy["body"] = ""
        art_copy["is_paywalled"] = False
        enriched_articles.append(art_copy)

    # Prioritize completely free, full-text articles over paywalled snippets
    enriched_articles.sort(
        key=lambda a: (1 if (not a.get("is_paywalled") and len(a.get("body", "")) > 500) else 0),
        reverse=True
    )

    # Build context string with full text
    articles_snippet = ""
    for idx, art in enumerate(enriched_articles):
        desc = art.get('description', '')
        body = art.get('body', '')
        is_pw = art.get('is_paywalled', False)
        
        pw_badge = " [PAYWALLED / SHORT TEASER]" if is_pw else ""
        text_to_show = body if (body and len(body) > 200) else desc
        if len(text_to_show) > 1800:
            text_to_show = text_to_show[:1800] + "..."
            
        articles_snippet += f"[{idx+1}] Title: {art['title']}{pw_badge}\nLink: {art['link']}\nContent:\n{text_to_show}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""You are a senior IT editor for a top Telegram tech channel.

Task 1: Check if any of these companies have layoffs/restructuring news: {companies_str}

Task 2: Write ONE Russian tech digest post summarizing ONE real, substantive IT/tech article from the list.

ALREADY PUBLISHED HEADLINES (DO NOT write about these events again):
{recent_topics_str}

ALREADY PUBLISHED TIPS (DO NOT repeat these tips, tools, or concepts):
{recent_tips_str}

CRITICAL ANTI-HALLUCINATION & FACTUALITY RULES (STRICT ZERO-HALLUCINATION POLICY):
1. ZERO HALLUCINATIONS: Every fact, company name, technical detail, and quote in your summary MUST be strictly grounded in the provided article content.
2. ABSOLUTELY DO NOT INVENT unmentioned facts. Do NOT make up new courses, curriculums, generative AI modules, DevOps tools, cloud partnerships, or educational programs unless they are EXPLICITLY written in the source text.
3. If an article is marked [PAYWALLED] or is only a short teaser, DO NOT expand it with imagined details. Write a concise, 100% truthful summary of only what is confirmed in the text.
4. If an article is purely administrative, unrelated to IT/programming, or lacks substance, IGNORE it and pick a better article from the list.
5. Priority: Real IT & Developer news in Denmark / Europe > Startups & Tech breakthroughs > General IT.

FORMATTING RULES (Telegram HTML):
- Use HTML tags: <b>bold</b>, <i>italic</i>, <code>code</code>, <a href="url">text</a>
- NO Markdown (* or _ or # or ```)!
- No leading spaces/tabs. Every line starts at column 0.
- Write in engaging, natural Russian, but keep the facts 100% accurate.

TEMPLATE (follow EXACTLY):
[Emoji: 🎓/⚖️/🔄/📰/🚀] <b>[Accurate, Catchy Headline in Russian]</b>

[1-3 paragraphs of clear, engaging text explaining the actual event, confirmed details, and real context as stated in the source article. Never embellish with fake facts.]

🔗 <a href="[original_link]">Читать полностью</a>

💡 <b>Полезно знать:</b> [1-2 sentences. Category for THIS post: {selected_category}. Write something practical and actionable from this category. It must be COMPLETELY DIFFERENT from everything in the "ALREADY PUBLISHED TIPS" list above.]

Articles:
{articles_snippet}

Return ONLY valid JSON:
{{
    "restructuring_companies": ["list of company names or empty list"],
    "digest_ru": "Your HTML-formatted Telegram post"
}}"""

    # 1. Try Gemini API first if key is available
    if config.GEMINI_API_KEY:
        gemini_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
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
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=1.5, min=2, max=10),
                        reraise=True
                    ):
                        with attempt:
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

                            is_valid = await autograde_digest(digest_ru, articles_snippet)
                            if not is_valid:
                                logger.warning(f"Autograder rejected digest from {g_model}. Trying next model.")
                                break
                                
                            logger.info(f"Successfully generated and validated digest via Gemini API model ({g_model})")
                            return parsed
            except Exception as e:
                logger.warning(f"Gemini API exception with model {g_model}: {e}")

    # 2. Fallback to Groq API if Gemini is unavailable or fails
    if config.GROQ_API_KEY:
        models_to_try = ["openai/gpt-oss-120b", "llama-3.1-8b-instant"]
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
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
                    async for attempt in AsyncRetrying(
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=1.5, min=2, max=10),
                        reraise=True
                    ):
                        with attempt:
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

                            is_valid = await autograde_digest(digest_ru, articles_snippet)
                            if not is_valid:
                                logger.warning(f"Autograder rejected digest from {model}. Trying next model.")
                                break
                                
                            logger.info(f"Successfully generated and validated digest via Groq fallback ({model})")
                            return parsed
            except Exception as e:
                logger.error(f"Groq API exception during news analysis with model {model}: {e}")

    return {"restructuring_companies": [], "digest_ru": ""}

async def process_news(state: dict, force_post: bool = False) -> dict:
    """Fetch news, analyze with LLM, and return restructuring companies, digest, and used term if new articles found."""
    raw_seen = state.get("seen_news", [])
    posted_news = state.get("posted_news", [])
    
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
    
    # Collect all target companies (fail fast if configuration is corrupted)
    import json as json_lib
    with open("target_companies.json", "r", encoding="utf-8") as f:
        target_companies = json_lib.load(f)
    
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

        # Semantic Deduplication across feeds using topic fingerprinting
        for art in articles:
            is_dupe = False
            for existing in all_articles:
                if existing["link"] == art["link"]:
                    is_dupe = True
                    break
                if is_topic_duplicate(art["title"], existing["title"]):
                    is_dupe = True
                    logger.debug(f"Cross-feed dedup: '{art['title'][:50]}' matches '{existing['title'][:50]}'")
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
            "posted_news_titles": []
        }

    # Filter out seen articles using topic fingerprint + link matching
    if force_post:
        logger.info("force_post is True, skipping seen_news check.")
        new_articles = all_articles
    else:
        new_articles = []
        for art in all_articles:
            is_dupe = False
            for seen in seen_news:
                # Check by link (exact URL match)
                if seen["link"] == art["link"]:
                    is_dupe = True
                    break
                # Check by topic (catches same story from different sources/days)
                if seen.get("title") and is_topic_duplicate(art["title"], seen["title"]):
                    is_dupe = True
                    logger.info(f"Topic dedup blocked: '{art['title'][:60]}' matches seen '{seen['title'][:60]}'")
                    break
            
            if not is_dupe:
                new_articles.append(art)
    
    if not new_articles:
        logger.info("No new news articles to process.")
        return {"restructuring_companies": [], "digests_ru": [], "seen_news": seen_news, "posted_news_titles": []}

    # Limit to top 10 candidate articles for a single digest post
    articles_to_process = new_articles[:10]
    logger.info(f"Found {len(new_articles)} new articles. Generating 1 single digest post from top {len(articles_to_process)} articles...")

    analysis = await ask_llm_news(articles_to_process, target_company_names, posted_news)
    digest_ru = analysis.get("digest_ru", "").strip()
    
    if not digest_ru:
        logger.warning("LLM generation failed for all models. Using high-quality full structure fallback digest.")
        digest_ru = build_quality_fallback_digest(articles_to_process)
        analysis["digest_ru"] = digest_ru
        
    digest_ru = analysis.get("digest_ru", "").strip()
    
    digests_ru = []
    posted_news_titles = []
    restructuring_comps = []

    if digest_ru:
        digests_ru.append(digest_ru)
        
        # Extract headline for future deduplication tracking
        headline_match = re.search(r'<b>(.*?)</b>', digest_ru)
        if headline_match:
            posted_news_titles.append(headline_match.group(1).strip())
        else:
            first_line = digest_ru.split('\n')[0][:100] # Fallback to first line
            posted_news_titles.append(first_line.strip())
        
        # Extract the "Полезно знать" tip text for separate tip deduplication
        tip_match = re.search(r'Полезно знать:</b>\s*(.+?)(?:\n|$)', digest_ru)
        if tip_match:
            posted_news_titles.append(f"TIP:{tip_match.group(1).strip()}")
            
        restructuring_comps.extend(analysis.get("restructuring_companies", []))

    # CRITICAL FIX: Mark ALL new articles as seen (not just processed ones)
    # This prevents articles at indexes 10+ from reappearing next run
    for art in new_articles:
        if not any(s["link"] == art["link"] for s in seen_news):
            seen_news.append({
                "link": art["link"],
                "title": art["title"],  # Always store title for topic matching
                "timestamp": art.get("timestamp", current_time)
            })

    # Dedup seen_news by link
    final_seen: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for s in seen_news:
        if s["link"] not in seen_links:
            seen_links.add(s["link"])
            final_seen.append(s)

    return {
        "restructuring_companies": list(set(restructuring_comps)),
        "digests_ru": digests_ru,
        "seen_news": final_seen,
        "posted_news_titles": posted_news_titles
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
