from __future__ import annotations
import httpx
import logging
import json
import asyncio
from typing import Any
from datetime import datetime
import config
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
from utils import extract_json_payload
logger = logging.getLogger("elevplads_scraper")

import feedparser
import re
import time

# Bilingual stopwords: Danish + English (for correct Jaccard across mixed-language feeds)
STOPWORDS = {
    # Danish
    "i", "af", "på", "med", "for", "at", "en", "et", "den", "det", "de", "til", "fra", "om",
    "er", "som", "vil", "har", "ikke", "der", "sig", "kan", "var", "også", "men", "da", "nu",
    "ud", "over", "under", "efter", "ny", "nyt", "nye", "mod", "mere", "mange", "flere",
    "blev", "bliver", "ved", "kun", "når", "andre", "meget", "alle", "denne", "disse",
    "skal", "her", "hvad", "hvordan", "hvorfor", "stor", "stort", "store",
    "og", "eller", "så", "vi",
    # English
    "the", "and", "for", "with", "that", "this", "its", "has", "are", "was", "were",
    "from", "will", "into", "been", "have", "had", "but", "not", "can", "all", "more",
    "than", "just", "now", "new", "how", "why", "what", "when", "who", "also", "about",
    "says", "said", "could", "would", "should", "being", "their", "them", "they", "some",
    "out", "its", "your", "you", "may", "two", "first", "most", "after", "before",
    "get", "got", "one", "set", "use", "way", "per", "via",
}
# Legacy alias for backward compatibility
DANISH_STOPWORDS = STOPWORDS

# Synonym groups: bilingual (DA+EN) words that represent the same event type.
# If two titles share a named entity AND a matching synonym group, they're about the same event.
SYNONYM_GROUPS = [
    # 0: Sandbox / Isolation
    {"sandbox", "sandkasse", "isoleret", "kontrolleret", "miljø", "miljøet", "isolation", "sandboxed", "containerized"},
    # 1: Escape / Breakout
    {"brød", "bryder", "undslap", "undslappet", "undslippe", "omgik", "omgå", "flygtede",
     "escapede", "broke", "escape", "escaped", "bypass", "bypassed", "bypasses", "breakout", "jailbreak"},
    # 2: AI Agent / Model
    {"agent", "model", "modellen", "agenten", "bot", "system", "kunstig", "intelligens"},
    # 3: Security / Vulnerability
    {"sikkerhed", "sikkerhedstest", "sikkerhedsforskere", "sikkerheds", "security",
     "vulnerability", "vulnerabilities", "exploit", "exploited", "zero-day", "zeroday", "cve",
     "sårbarhed", "sårbarheder", "sikkerhedsbrist"},
    # 4: Layoff / Firing / Restructuring
    {"fyring", "fyringer", "fyrer", "fyret", "afskedigelse", "afskedigelser", "nedskæringer", "nedskæring",
     "opsigelse", "opsigelser", "layoff", "layoffs", "laid", "fires", "fired", "firing", "cuts",
     "restructuring", "restrukturering", "downsizing"},
    # 5: Hiring / Recruitment
    {"ansætter", "ansættelse", "ansættelser", "rekrutterer", "rekruttering",
     "hiring", "hires", "recruits", "recruitment"},
    # 6: Hack / Breach / Leak
    {"hacket", "hacking", "hack", "hackere", "cyberangreb", "databrud",
     "breach", "breached", "leaked", "leak", "lækket", "læk", "compromised"},
    # 7: Launch / Release / Announce / Unveil
    {"lancerer", "lancering", "præsenterer", "præsentation", "annoncerer", "annoncering",
     "offentliggør", "udgivelse", "release", "released", "releases", "launches", "launched",
     "launch", "announces", "announced", "unveils", "unveiled", "reveals", "revealed",
     "introduces", "introduced", "debuts", "ships", "shipped", "rolls out"},
    # 8: Acquisition / Merger / Buyout
    {"opkøb", "opkøber", "køber", "køb", "acquisition", "acquires", "acquired",
     "overtager", "overtagelse", "fusionerer", "fusion", "merger", "buyout", "takeover"},
    # 9: Apprentice / Education
    {"elev", "elevplads", "elevpladser", "lærling", "lærlinge", "læreplads", "lærepladser", "apprentice"},
    # 10: Outage / Downtime / Crash
    {"nedbrud", "afbrydelse", "nede", "outage", "downtime", "down", "crash", "crashed",
     "disruption", "forstyrrelse", "offline"},
    # 11: Benchmark / Performance / Record
    {"benchmark", "benchmarks", "benchmarked", "performance", "ydelse", "hastighed",
     "record", "rekord", "rekordstor", "fastest", "hurtigste"},
    # 12: Production / Manufacturing / Fabrication
    {"produktion", "producetion", "production", "manufacturing", "fabrication", "fabrikation",
     "masseproduktion"},
]

# Key named entities that anchor topic identity (120+ brands, platforms, languages, chips)
KEY_ENTITIES = {
    # AI / LLM companies & models
    "openai", "chatgpt", "gpt", "anthropic", "claude", "deepmind", "gemini", "deepseek",
    "mistral", "llama", "meta", "copilot", "huggingface", "perplexity", "midjourney",
    "stability", "cohere",
    # Big Tech
    "google", "microsoft", "apple", "amazon", "aws", "nvidia", "tesla", "samsung",
    "oracle", "ibm", "salesforce", "adobe", "netflix", "spotify", "uber",
    # Semiconductor & Hardware
    "amd", "intel", "tsmc", "arm", "qualcomm", "broadcom", "mediatek", "asml",
    "micron", "sk hynix", "risc-v",
    # Cloud & Infrastructure
    "cloudflare", "fastly", "hashicorp", "terraform", "datadog", "snowflake",
    "docker", "kubernetes", "github", "gitlab",
    # Programming Languages & Runtimes
    "rust", "golang", "zig", "swift", "kotlin", "python", "typescript", "deno", "bun",
    "dotnet", "java", "elixir", "haskell", "clojure", "nim", "odin", "mojo", "julia",
    # Databases
    "postgresql", "postgres", "redis", "sqlite", "mysql", "mongodb", "clickhouse",
    "cockroachdb", "supabase", "neon", "turso",
    # OS & Distributions
    "linux", "debian", "ubuntu", "fedora", "arch", "nixos", "android", "ios", "macos",
    "windows", "freebsd", "chromeos",
    # Browsers
    "chrome", "chromium", "firefox", "safari", "webkit",
    # Game Engines & Graphics
    "unreal", "unity", "godot", "webgpu", "vulkan", "directx", "opengl",
    "cryengine", "lumberyard",
    # Security
    "crowdstrike", "palo alto", "fortinet", "mandiant", "sentinelone",
    # Social / Communication
    "twitter", "threads", "instagram", "whatsapp", "signal", "telegram",
    "tiktok", "discord", "slack", "zoom",
    # Infra / Space
    "spacex", "starlink",
    # Danish Education
    "aub", "eud", "eux", "datatekniker",
}

# ─── 6 IT CATEGORIES for diverse candidate selection ───
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "systems_dev": [
        "linux kernel", "kernel", "compiler", "compilers", "llvm", "gcc", "clang",
        "postgresql", "postgres", "sqlite", "mysql", "redis", "clickhouse", "cockroachdb",
        "database", "rust", "golang", "zig", "swift", "kotlin", "elixir", "haskell", "mojo",
        "typescript", "javascript", "python", "c#", "dotnet", ".net", "java", "deno", "bun",
        "docker", "kubernetes", "k8s", "terraform", "ansible", "nixos", "nix",
        "open source", "open-source", "git", "github", "gitlab",
        "microservices", "monolith", "api", "grpc", "graphql",
        "distributed systems", "consensus", "raft", "paxos",
        "backend", "frontend", "framework", "devops", "cicd", "ci/cd",
        "linux", "freebsd", "debian", "ubuntu", "fedora", "arch",
        "wasm", "webassembly", "runtime", "jit",
    ],
    "hardware_chips": [
        "amd", "intel", "tsmc", "arm", "risc-v", "qualcomm", "broadcom", "mediatek",
        "asml", "micron", "sk hynix", "samsung",
        "cpu", "gpu", "npu", "tpu", "processor", "microarchitecture",
        "zen", "raptor lake", "arrow lake", "meteor lake",
        "nanometer", "2nm", "3nm", "5nm", "7nm",
        "ddr5", "ddr6", "hbm", "pcie", "nvme", "ssd", "nand", "dram",
        "chip", "chips", "semiconductor", "halvleder", "transistor",
        "motherboard", "bundkort", "overclocking",
        "quantum", "kvante", "qubit", "superconducting",
        "robotik", "humanoid", "robot", "spacex", "starlink",
    ],
    "infosec": [
        "zero-day", "0day", "cve", "exploit", "vulnerability", "sårbarhed",
        "reverse engineering", "side-channel", "spectre", "meltdown",
        "cryptography", "encryption", "tls", "ssl", "post-quantum",
        "pentesting", "red team", "blue team", "bug bounty",
        "crowdstrike", "mandiant", "sentinelone", "fortinet",
        "apt", "threat actor", "nation-state",
        "privilege escalation", "rce", "remote code execution",
        "use-after-free", "buffer overflow", "memory safety",
    ],
    "gamedev_graphics": [
        "unreal engine", "unity", "godot", "cryengine",
        "webgpu", "vulkan", "directx", "opengl", "metal",
        "ray tracing", "path tracing", "nanite", "lumen", "dlss", "fsr",
        "shaders", "shader", "rendering", "renderer",
        "game engine", "game dev", "gamedev", "spiludvikling",
        "fps", "rpg", "mmorpg", "indie game",
        "playstation", "ps5", "ps6", "xbox", "nintendo", "switch 2", "steam",
        "vr", "ar", "xr", "virtual reality", "mixed reality",
        "procedural generation", "physics engine",
        "io interactive", "playdead", "sybo",
    ],
    "ai_ml": [
        "llm", "large language model", "transformer", "attention mechanism",
        "mixture of experts", "moe", "rag", "fine-tuning", "rlhf", "dpo",
        "inference", "training", "gpu cluster", "tpu pod",
        "openai", "anthropic", "deepseek", "mistral", "llama", "gemini",
        "chatgpt", "claude", "copilot", "midjourney", "stable diffusion",
        "neural network", "deep learning", "machine learning",
        "ai-model", "ai model", "foundation model",
        "computer vision", "nlp", "multimodal",
        "huggingface", "mlops",
    ],
    "tech_trends": [
        "startup", "funding", "ipo", "valuation",
        "open source", "license", "sustainability",
        "privacy", "gdpr", "regulation",
        "denmark", "danish", "dansk", "european", "eu",
        "supercomputer", "datacenter", "data center",
        "5g", "6g", "satellite", "fiber",
        "apple", "google", "amazon", "meta", "microsoft",
        "cloud", "edge computing", "iot",
    ],
}

# Compile category patterns for fast matching
_CATEGORY_PATTERNS: dict[str, re.Pattern] = {}
for _cat, _kws in CATEGORY_KEYWORDS.items():
    _pattern = r'\b(?:' + '|'.join(map(re.escape, sorted(_kws, key=len, reverse=True))) + r')\b'
    _CATEGORY_PATTERNS[_cat] = re.compile(_pattern, re.IGNORECASE)


def classify_article_category(title: str, description: str = "") -> str:
    """Classify an article into one of 6 IT categories using keyword matching.
    Returns the category with the most keyword hits. Falls back to 'tech_trends'."""
    text = f"{title} {description}".lower()
    scores: dict[str, int] = {}
    for cat, pattern in _CATEGORY_PATTERNS.items():
        hits = len(pattern.findall(text))
        if hits > 0:
            scores[cat] = hits
    if not scores:
        return "tech_trends"
    return max(scores, key=scores.get)


# Danish Tech, Gaming & IT Education keywords for broad feeds (e.g. DR.dk)
DR_TECH_KEYWORDS = [
    "ai", "kunstig intelligens", "it-uddannelse", "datatekniker", "erhvervsuddannelse",
    "eud", "eux", "it-sikkerhed", "cyber", "teknologi", "software",
    "supercomputer", "datacenter", "digitalisering", "mitid", "tech", "datalogi",
    "kodning", "algoritme", "robot", "cloud", "it-system",
    "læreplads", "skoleoplæring", "it-branchen", "tech-giganter", "meta", "google",
    "apple", "microsoft", "openai", "nvidia", "deepseek", "chatgpt",
    # Gaming, GameDev, 3D & Graphics
    "spil", "gaming", "spiludvikling", "gamedev", "playstation", "xbox", "nintendo",
    "unreal engine", "unity", "grafikkort", "gpu", "ray tracing", "konsol", "steam"
]
DR_TECH_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, DR_TECH_KEYWORDS)) + r')\b', re.IGNORECASE)

WOW_TECH_PATTERNS = [
    # Gaming & GameDev & 3D Graphics & Consoles & WebGPU
    r'\b(?:spil|gaming|gamer|spiludvikling|gamedev|game engine|unreal engine|unity|godot|grafik|graphics|ray tracing|path tracing|dlss|fsr|webgpu|vulkan|directx|shaders|playstation|ps5|xbox|nintendo|switch 2|steam|gpu|geforce|rtx|radeon|gameplay|konsol|spilbranche|io interactive|playdead|sybo|fps|rpg|vr|virtual reality|game dev|procedural)\b',
    # Programming, Software Architecture, Tools, Compilers & Releases
    r'\b(?:developer|udvikler|programmering|softwareudvikling|open source|framework|compiler|c#|\.net|dotnet|python|rust|golang|zig|swift|kotlin|typescript|javascript|api|arkitektur|architecture|database|github|gitlab|docker|kubernetes|linux kernel|release|algoritme|backend|frontend|microservices|wasm|webassembly)\b',
    # AI Models, Quantum, Chips & Breakthrough Engineering
    r'\b(?:gennembrud|breakthrough|revolution|supercomputer|kvante|quantum|chip|chips|halvleder|semiconductor|processor|robot|robotik|humanoid|autonom|llm|ai-model|deepseek|openai|chatgpt|gpt-5|gpt-6|anthropic|claude|gemini|neural|innovation|opfindelse|fremtidens teknologi)\b',
    # Hardware, CPUs, GPUs, Memory, Storage & Microarchitecture (NEW — was a blind spot)
    r'\b(?:amd|intel|tsmc|arm|risc-v|qualcomm|broadcom|asml|micron|cpu|npu|tpu|microarchitecture|zen\s?\d|nanometer|2nm|3nm|5nm|ddr5|ddr6|hbm|pcie|nvme|ssd|nand|dram|transistor|fab|foundry|die|wafer|lithography|euv)\b',
    # Systems Engineering, Databases, Runtimes & Protocols (NEW — was a blind spot)
    r'\b(?:postgresql|postgres|sqlite|redis|clickhouse|mongodb|cockroachdb|mysql|supabase|neon|turso|grpc|graphql|websockets|distributed|consensus|raft|paxos|etcd|nixos|nix|deno|bun|llvm|gcc|clang|jit|ebpf|io_uring)\b',
]

ROUTINE_INCIDENT_PATTERNS = [
    # Municipal/administrative dull incidents only (compound context required).
    # Deep infosec (zero-day, side-channel, kernel exploit) is NOT penalized.
    r'\b(?:nedbrud|it-svigt|retssag|stævning|sagsøgt|datatilsynet|bøde|bødeforlæg|kritik af|kontraktstrid|udbudsskandale|slettefejl|møgsag|aktindsigt|skattestyrelsen|it-kriminalitet|afpresning)\b',
    # Routine mass-incident spam (phishing alerts, generic ransomware/DDoS reports with no technical depth)
    r'\b(?:kommune ramt|skole ramt|hospital ramt|politiet advarer|svindel|fup)\b',
    # Only penalize phishing/ransomware/ddos in context of routine alerts, not deep analysis
    r'(?:advarer|ramt|rammes|rammer|angriber).*?\b(?:phishing|ransomware|ddos)\b',
    r'\b(?:phishing|ransomware|ddos)\b.*?(?:advarer|ramt|rammes|rammer|angriber)',
]

def calculate_interest_score(title: str, description: str = "") -> int:
    """Score articles by technical excitement, game development, programming, and innovation vs dull routine incidents."""
    text = f"{title} {description}".lower()
    score = 0
    for pat in WOW_TECH_PATTERNS:
        matches = len(re.findall(pat, text, re.IGNORECASE))
        score += matches * 4
    for pat in ROUTINE_INCIDENT_PATTERNS:
        matches = len(re.findall(pat, text, re.IGNORECASE))
        score -= matches * 6
    return score

def clean_tokens(s: str) -> set[str]:
    words = re.findall(r'\w+', s.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}

def extract_version_markers(title: str) -> set[str]:
    """Extract version numbers and spec markers for precise dedup (e.g. 'rtx 5090', 'zen 5', 'linux 6.14')."""
    text = title.lower()
    markers: set[str] = set()
    # Patterns: "word number" or "word-number" (e.g. "ryzen 9000", "gpt-5", "linux 6.14")
    for m in re.finditer(r'([a-z]+)[\s\-](\d+(?:\.\d+)?)', text):
        markers.add(f"{m.group(1)}_{m.group(2)}")
    # Raw model numbers like "5090", "9000" when preceded by known product lines
    return markers

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

    # 3. Add version markers (e.g. "ryzen_9000", "gpt_5", "linux_6.14")
    version_markers = extract_version_markers(title)
    for vm in version_markers:
        fingerprint.add(f"ver:{vm}")

    return fingerprint

def is_topic_duplicate(title1: str, title2: str) -> bool:
    """Check if two titles are about the same topic/event.
    Uses a combination of: exact normalized matching, entity overlap, synonym group matching,
    version marker matching, and Jaccard similarity."""
    if not title1 or not title2:
        return False

    # Layer 0: Exact normalized title match (ignoring punctuation, casing, extra whitespace)
    norm1 = re.sub(r'[^\w\s]', '', title1.lower()).strip()
    norm2 = re.sub(r'[^\w\s]', '', title2.lower()).strip()
    if norm1 == norm2:
        return True

    # Layer 1: Direct Jaccard on cleaned tokens (catches obvious dupes)
    set1 = clean_tokens(title1)
    set2 = clean_tokens(title2)
    if set1 and set2:
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        jaccard = len(intersection) / len(union)
        if jaccard > 0.45:
            return True

    # Layer 2: Topic fingerprint matching
    fp1 = get_topic_fingerprint(title1)
    fp2 = get_topic_fingerprint(title2)

    if not fp1 or not fp2:
        return False

    # Extract entities, synonyms, and version markers
    entities1 = {t for t in fp1 if not t.startswith(("syn:", "ver:"))}
    entities2 = {t for t in fp2 if not t.startswith(("syn:", "ver:"))}
    shared_entities = entities1 & entities2

    vers1 = {t for t in fp1 if t.startswith("ver:")}
    vers2 = {t for t in fp2 if t.startswith("ver:")}
    shared_vers = vers1 & vers2

    syns1 = {t for t in fp1 if t.startswith("syn:")}
    syns2 = {t for t in fp2 if t.startswith("syn:")}
    shared_syns = syns1 & syns2

    if not shared_entities:
        return False

    # Entity + synonym match → same event
    if shared_entities and shared_syns:
        return True

    # Entity + version marker match → same product/release (e.g. "ryzen_9000")
    if shared_entities and shared_vers:
        return True

    # 2+ shared entities → same topic even without synonym/version
    if len(shared_entities) >= 2:
        return True

    return False


def select_diverse_candidates(articles: list[dict], state: dict) -> list[dict]:
    """Select a balanced basket of candidates: best article from each distinct category,
    with cooldown penalties for recently posted categories and entities."""
    posted_records = state.get("posted_news_records", [])
    
    # Compute recent categories and entities from posted_news_records (last 10)
    recent_cats = [r.get("category", "") for r in posted_records[-10:]]
    recent_ents = set()
    for r in posted_records[-10:]:
        recent_ents.update(r.get("entities", []))

    # Classify and score each article with cooldown adjustments
    for art in articles:
        cat = classify_article_category(art["title"], art.get("description", ""))
        art["category"] = cat
        
        base_score = art.get("interest_score", 0)
        
        # Cooldown penalties
        if recent_cats and cat == recent_cats[-1]:
            base_score -= 12  # Last posted category penalty
        elif cat in recent_cats:
            base_score -= 6   # Recently posted category penalty
        
        # Entity cooldown: penalize if article's main entities were recently posted
        art_entities = {t for t in clean_tokens(art["title"]) if t in KEY_ENTITIES}
        art["detected_entities"] = list(art_entities)
        overlap_count = len(art_entities & recent_ents)
        if overlap_count > 0:
            base_score -= overlap_count * 10
        
        # Freshness bonus for underrepresented categories
        if cat not in recent_cats:
            base_score += 8
        
        # Breaking News Override: if original score was very high, don't let cooldown kill it
        if art.get("interest_score", 0) > 20:
            base_score = max(base_score, art["interest_score"] - 4)
        
        art["adjusted_score"] = base_score

    # Build basket: pick best article per category, then fill remaining slots
    best_per_cat: dict[str, dict] = {}
    for art in articles:
        cat = art["category"]
        if cat not in best_per_cat or art["adjusted_score"] > best_per_cat[cat]["adjusted_score"]:
            best_per_cat[cat] = art

    # Order: prioritize categories not in recent_cats
    category_order = ["systems_dev", "hardware_chips", "infosec", "gamedev_graphics", "ai_ml", "tech_trends"]
    basket: list[dict] = []
    used_links: set[str] = set()
    
    # First pass: categories not recently posted
    for cat in category_order:
        if cat in best_per_cat and cat not in recent_cats:
            art = best_per_cat[cat]
            if art["link"] not in used_links:
                basket.append(art)
                used_links.add(art["link"])
    
    # Second pass: remaining categories
    for cat in category_order:
        if cat in best_per_cat and best_per_cat[cat]["link"] not in used_links:
            basket.append(best_per_cat[cat])
            used_links.add(best_per_cat[cat]["link"])
    
    # Fill up to 6 with next-best articles not yet included
    remaining = sorted(
        [a for a in articles if a["link"] not in used_links],
        key=lambda x: x.get("adjusted_score", 0), reverse=True
    )
    for art in remaining:
        if len(basket) >= 6:
            break
        basket.append(art)
        used_links.add(art["link"])

    return basket

async def fetch_rss(url: str, source_name: str = "") -> tuple[list[dict], bool]:
    """Fetch and parse RSS/Atom feed into a list of articles using feedparser and httpx. Returns (articles, success_flag)."""
    articles = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/rdf+xml, application/atom+xml, application/xml, text/xml, */*"
    }
    try:
        client_kwargs: dict[str, Any] = {"timeout": 15.0, "follow_redirects": True}
        if getattr(config, "PROXY_URL", None):
            client_kwargs["proxy"] = config.PROXY_URL
        async with httpx.AsyncClient(**client_kwargs) as client:
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
                    
                    # If fetching from a broad national source like DR, apply strict IT & Education keyword filtering
                    if source_name.startswith("DR"):
                        combined_text = f"{title} {description}".lower()
                        if not DR_TECH_PATTERN.search(combined_text):
                            continue

                    if title and link:
                        articles.append({
                            "title": title,
                            "link": link,
                            "description": description or "",
                            "timestamp": timestamp,
                            "source": source_name
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
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



async def autograde_digest(digest_ru: str, snippets: str) -> bool:
    """Check for hallucinations, fabricated courses, and ungrounded claims in the news summary."""
    # Strip the educational developer tip at the bottom so it doesn't cause a false positive
    news_body = digest_ru
    if "💡" in news_body:
        news_body = news_body.split("💡")[0].strip()
    elif "Полезно знать" in news_body:
        news_body = news_body.split("Полезно знать")[0].strip()

    prompt = f"""Source article text:
{snippets[:3500]}

Generated Russian News Summary:
{news_body}

Fact-Check Task:
Compare the generated Russian news summary against the source text.
Does the summary invent fake facts, non-existent people, or fake events not mentioned in the source?
(Note: stylistic rewriting or translating into engaging Russian is completely fine. Only flag if it invents completely made-up facts).

Return JSON ONLY:
{{
    "is_faithful": true,
    "reason": "Brief explanation"
}}"""

    if config.GEMINI_API_KEY:
        for g_model in ["gemini-3.8-flash", "gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-flash-lite"]:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{g_model}:generateContent?key={config.GEMINI_API_KEY}"
            payload: dict[str, Any] = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.1
                }
            }
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                        data = extract_json_payload(text)
                        if data.get("is_faithful") is False:
                            logger.warning(f"Autograder BLOCKED hallucinated digest ({g_model}): {data.get('reason')}")
                            return False
                        return True
            except Exception as e:
                logger.warning(f"Autograder check error ({g_model}): {e}")

    # Fallback to Groq for autograding
    if config.GROQ_API_KEY:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}", "Content-Type": "application/json"}
            payload = {
                "model": "openai/gpt-oss-20b",
                "messages": [
                    {"role": "system", "content": "You are a JSON fact-checker. Output ONLY valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 150
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    data = extract_json_payload(text)
                    if data.get("is_faithful") is False:
                        logger.warning(f"Autograder (Groq) BLOCKED hallucinated digest: {data.get('reason')}")
                        return False
                    return True
        except Exception as e:
            logger.warning(f"Autograder check error (Groq fallback): {e}")

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

def get_next_tip_term(pool: list[str], tip_history: dict[str, str]) -> str:
    """tip_history: {term: last_used_iso_date}.
    Возвращает никогда не использованный термин, либо термин с самой старой датой."""
    unused = [t for t in pool if t not in tip_history]
    if unused:
        return unused[0]
    return min(tip_history, key=tip_history.get)

async def ask_llm_news(articles: list[dict], target_companies: list[str], posted_news: list[str], state: dict | None = None) -> dict:
    """
    Pass articles to LLM to check for layoffs/restructuring
    and to generate a single Russian digest post with strict factual grounding.
    """
    tip_history = state.get("tip_history", {}) if state else {}
    selected_category = get_next_tip_term(config.TECH_TERMS_POOL, tip_history)

    if (not config.GEMINI_API_KEY and not config.GROQ_API_KEY) or not articles:
        return {"restructuring_companies": [], "digest_ru": "", "selected_tip_term": selected_category}

    # Build dedup context from posted_news_records (original titles) + legacy posted_news
    posted_records = state.get("posted_news_records", []) if state else []
    recent_headlines = [r.get("original_title", r.get("headline_ru", "")) for r in posted_records[-15:]]
    # Also include legacy posted_news headlines
    legacy_headlines = [t for t in posted_news if not t.startswith("TIP:")]
    all_recent = list(dict.fromkeys(recent_headlines + legacy_headlines))[-15:]  # dedup, keep order
    recent_topics_str = "\n".join([f"- {t}" for t in all_recent]) if all_recent else "None"

    # Enrich candidate articles with real webpage text in parallel
    async def enrich_article(art: dict) -> dict:
        body, is_paywalled = await fetch_article_content(art.get("link", ""))
        art_copy = dict(art)
        art_copy["body"] = body
        art_copy["is_paywalled"] = is_paywalled
        # Preserve category and entities from select_diverse_candidates
        art_copy["category"] = art.get("category", "tech_trends")
        art_copy["detected_entities"] = art.get("detected_entities", [])
        return art_copy

    logger.info("Fetching full article texts for candidate news...")
    # Enrich up to 6 articles (category-balanced basket from select_diverse_candidates)
    enriched_articles = await asyncio.gather(*[enrich_article(a) for a in articles[:6]])

    # Prioritize completely free, full-text articles over paywalled snippets
    enriched_articles.sort(
        key=lambda a: (1 if (not a.get("is_paywalled") and len(a.get("body", "")) > 300) else 0),
        reverse=True
    )

    # Category display names for prompt badges
    cat_display = {
        "systems_dev": "Systems & Software Engineering",
        "hardware_chips": "Hardware & Semiconductors",
        "infosec": "Cybersecurity & Exploits",
        "gamedev_graphics": "GameDev & 3D Graphics",
        "ai_ml": "AI & Machine Learning",
        "tech_trends": "Tech Trends & Industry",
    }

    # Build compact context string with category badges and full text
    articles_snippet = ""
    for idx, art in enumerate(enriched_articles[:6]):
        desc = art.get('description', '')
        body = art.get('body', '')
        is_pw = art.get('is_paywalled', False)
        cat = art.get('category', 'tech_trends')
        
        cat_badge = f" [Category: {cat_display.get(cat, cat)}]"
        pw_badge = " [PAYWALLED / SHORT TEASER]" if is_pw else ""
        text_to_show = body if (body and len(body) > 150) else desc
        if len(text_to_show) > 800:
            text_to_show = text_to_show[:800] + "..."
            
        articles_snippet += f"[{idx+1}] Title: {art['title']}{cat_badge}{pw_badge}\nLink: {art['link']}\nContent:\n{text_to_show}\n\n"

    companies_str = ", ".join(target_companies)

    prompt = f"""You are a senior IT editor for a top Telegram tech & developer channel.

Task 1: Check if any of these companies have layoffs/restructuring news: {companies_str}

Task 2: Write ONE Russian tech digest post summarizing the MOST EXCITING, SUBSTANTIVE, and INNOVATIVE article from the list.

Each article is tagged with a [Category]. You have a diverse mix of categories: systems engineering, hardware, security, game development, AI, and general tech trends. PRIORITIZE VARIETY — choose the most technically deep and exciting article, BUT AVOID repeating the same category or company as recent posts.

ALREADY PUBLISHED HEADLINES (DO NOT write about these events or topics again):
{recent_topics_str}

CRITICAL EDITORIAL & CONTENT PRIORITIES:
- HIGHEST PRIORITY: Deep engineering content — Linux kernel patches, compiler innovations, database internals, CPU/GPU microarchitecture, semiconductor breakthroughs, zero-day exploit analysis, game engine rendering tech, novel algorithms, and systems programming.
- ALSO HIGH PRIORITY: Game development & gaming industry engineering (Unreal Engine, Unity, Godot, WebGPU/Vulkan, ray tracing), developer tools, modern programming languages (Rust, Zig, Go, C#, TypeScript), substantive AI/ML architecture (not marketing fluff).
- STRICTLY DE-PRIORITIZE: Routine cyberattacks, malware alerts, standard ransomware, pricing updates, petty data privacy fines, municipal IT downtime, or bureaucratic court battles.
- ROTATE TOPICS: If recent posts covered AI, choose hardware or systems. If recent posts covered hardware, choose gamedev or infosec. Keep the channel diverse and exciting!

CRITICAL ANTI-HALLUCINATION & FACTUALITY RULES (STRICT ZERO-HALLUCINATION POLICY):
1. ZERO HALLUCINATIONS: Every fact, company name, technical detail, and quote in your news summary MUST be strictly grounded in the provided article content.
2. ABSOLUTELY DO NOT INVENT unmentioned facts in the news section.
3. If an article is marked [PAYWALLED] or is only a short teaser, write a concise summary of only what is confirmed in the text.

FORMATTING RULES (Telegram HTML):
- Use HTML tags: <b>bold</b>, <i>italic</i>, <code>code</code>, <a href="url">text</a>
- NO Markdown (* or _ or # or ``` for formatting)!
- No leading spaces/tabs. Every line starts at column 0.
- Write in engaging, natural Russian, but keep the facts 100% accurate.
- At the very bottom of the post, add 3-5 relevant hashtags (e.g. #security #architecture #ai #csharp #devops #denmark #database #networking #programming #git #cleanarchitecture).

TEMPLATE (follow EXACTLY):
[Emoji: 🎓/⚖️/🔄/📰/🚀] <b>[Accurate, Catchy Headline in Russian]</b>

[1-3 paragraphs of clear, engaging text explaining the actual event, confirmed details, and real context as stated in the source article. Never embellish with fake facts.]

🔗 <a href="[original_link]">Читать полностью</a>

💡 <b>Полезно знать: [Concept / Technology Name]</b>

[1-2 clear, concise sentences explaining the concept/technology/pattern.]
• [Key technical fact / how it works under the hood / conditions]
• [Where it is applied in practice / engineering benefit / how to solve the problem]

#[tag1] #[tag2] #[tag3] #[tag4]

(Note for 'Полезно знать': Term for THIS post: {selected_category}.
Write EXACTLY about this term — do not substitute a different concept.
Explain it like to a self-taught junior developer: start with ONE vivid, everyday analogy in plain Russian, NO jargon in that first sentence.
Then one short "as it works" sentence. Avoid textbook/dry phrasing.)

Articles:
{articles_snippet}

Return ONLY valid JSON:
{{
    "restructuring_companies": ["list of company names or empty list"],
    "digest_ru": "Your HTML-formatted Telegram post"
}}"""

    # 1. Try Gemini API first if key is available
    if config.GEMINI_API_KEY:
        gemini_models = [
            "gemini-3.8-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite"
        ]
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
                            parsed["selected_tip_term"] = selected_category
                            return parsed
            except Exception as e:
                logger.warning(f"Gemini API exception with model {g_model}: {e}")

    # 2. Fallback to Groq API if Gemini is unavailable or fails
    if config.GROQ_API_KEY:
        models_to_try = ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
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
                            parsed["selected_tip_term"] = selected_category
                            return parsed
            except Exception as e:
                logger.error(f"Groq API exception during news analysis with model {model}: {e}")

    return {"restructuring_companies": [], "digest_ru": "", "selected_tip_term": selected_category}

async def process_news(state: dict, force_post: bool = False) -> dict:
    """Fetch news, analyze with LLM, and return restructuring companies, digest, and used term if new articles found."""
    raw_seen = state.get("seen_news", [])
    posted_news = state.get("posted_news", [])
    posted_records = state.get("posted_news_records", [])
    
    from datetime import timezone
    current_time = datetime.now(timezone.utc).timestamp()
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

    # Prune posted_news_records older than 10 days
    posted_records = [r for r in posted_records if current_time - r.get("timestamp", 0) <= 864000]
    
    # Collect all target companies (fail fast if configuration is corrupted)
    import json as json_lib
    target_path = getattr(config, "TARGET_COMPANIES_PATH", "target_companies.json")
    with open(target_path, "r", encoding="utf-8") as f:
        target_companies = json_lib.load(f)
    
    target_company_names = [c["name"] for c in target_companies]
    target_company_names.extend([c["name"] for c in state.get("dynamic_companies", [])])
    target_company_names = list(set(target_company_names)) # dedup

    all_articles: list[dict[str, Any]] = []
    feed_failures = state.get("feed_failures", {})

    for source, url in config.RSS_FEEDS.items():
        articles, success = await fetch_rss(url, source_name=source)
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
            "posted_news_titles": [],
            "posted_news_records": posted_records
        }

    # Filter out seen articles AND posted_news_records using topic fingerprint + link matching
    if force_post:
        logger.info("force_post is True, skipping seen_news check.")
        new_articles = all_articles
    else:
        # Build combined dedup pool: seen_news + posted_news_records (original titles)
        dedup_pool: list[dict[str, str]] = []
        for seen in seen_news:
            dedup_pool.append({"link": seen.get("link", ""), "title": seen.get("title", "")})
        for rec in posted_records:
            dedup_pool.append({"link": rec.get("link", ""), "title": rec.get("original_title", "")})
        
        new_articles = []
        for art in all_articles:
            is_dupe = False
            for pool_item in dedup_pool:
                # Check by link (exact URL match)
                if pool_item["link"] and pool_item["link"] == art["link"]:
                    is_dupe = True
                    break
                # Check by topic (catches same story from different sources/days/languages)
                if pool_item.get("title") and is_topic_duplicate(art["title"], pool_item["title"]):
                    is_dupe = True
                    logger.info(f"Topic dedup blocked: '{art['title'][:60]}' matches '{pool_item['title'][:60]}'")
                    break
            
            if not is_dupe:
                new_articles.append(art)
    
    if not new_articles:
        logger.info("No new news articles to process.")
        return {"restructuring_companies": [], "digests_ru": [], "seen_news": seen_news, "posted_news_titles": [], "posted_news_records": posted_records}

    # Score articles by technical innovation, gaming, and dev excitement vs dull incidents
    for art in new_articles:
        art["interest_score"] = calculate_interest_score(art["title"], art.get("description", ""))

    # Sort primarily by interest_score descending, secondarily by timestamp descending
    new_articles.sort(key=lambda x: (x.get("interest_score", 0), x.get("timestamp", 0)), reverse=True)

    # Select candidate articles with source diversity (max 2 per source) to prevent any single outlet from dominating
    articles_to_process: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for art in new_articles:
        src = art.get("source", "Unknown")
        if source_counts.get(src, 0) < 2:
            articles_to_process.append(art)
            source_counts[src] = source_counts.get(src, 0) + 1
        if len(articles_to_process) >= 15:  # Expanded pool for diverse selection
            break

    if not articles_to_process:
        articles_to_process = new_articles[:15]

    # Apply category-balanced diverse selection with cooldown
    diverse_basket = select_diverse_candidates(articles_to_process, state)
    
    cats_in_basket = set(a.get("category", "?") for a in diverse_basket)
    top_title = diverse_basket[0].get('title', '')[:50] if diverse_basket else 'None'
    logger.info(f"Found {len(new_articles)} new articles. Diverse basket: {len(diverse_basket)} articles across {cats_in_basket}. Top: '{top_title}'")

    analysis = await ask_llm_news(diverse_basket, target_company_names, posted_news, state=state)
    digest_ru = analysis.get("digest_ru", "").strip()
    selected_tip_term = analysis.get("selected_tip_term", "")
    
    if not digest_ru:
        logger.warning("LLM generation failed for all models. Using high-quality full structure fallback digest.")
        digest_ru = build_quality_fallback_digest(diverse_basket)
        analysis["digest_ru"] = digest_ru
        
    digest_ru = analysis.get("digest_ru", "").strip()
    
    digests_ru = []
    posted_news_titles = []
    restructuring_comps = []
    new_posted_records: list[dict[str, Any]] = []

    if digest_ru:
        digests_ru.append(digest_ru)
        
        # Extract headline for future deduplication tracking
        headline_match = re.search(r'<b>(.*?)</b>', digest_ru)
        headline_ru = ""
        if headline_match:
            headline_ru = headline_match.group(1).strip()
            posted_news_titles.append(headline_ru)
        else:
            first_line = digest_ru.split('\n')[0][:100]
            headline_ru = first_line.strip()
            posted_news_titles.append(headline_ru)

        # Try to identify which article the LLM chose (by link match in digest)
        chosen_art = None
        for art in diverse_basket:
            if art.get("link", "") and art["link"] in digest_ru:
                chosen_art = art
                break
        if not chosen_art and diverse_basket:
            chosen_art = diverse_basket[0]  # fallback to first candidate

        if chosen_art:
            new_posted_records.append({
                "headline_ru": headline_ru,
                "original_title": chosen_art.get("title", ""),
                "link": chosen_art.get("link", ""),
                "category": chosen_art.get("category", "tech_trends"),
                "entities": chosen_art.get("detected_entities", []),
                "timestamp": current_time
            })
            
        restructuring_comps.extend(analysis.get("restructuring_companies", []))

    # Mark all evaluated candidates as seen to prevent repeated LLM re-scoring
    for art in new_articles:
        if not any(s["link"] == art["link"] for s in seen_news):
            seen_news.append({
                "link": art["link"],
                "title": art["title"],
                "timestamp": art.get("timestamp", current_time)
            })

    # Dedup seen_news by link
    final_seen: list[dict[str, Any]] = []
    seen_links: set[str] = set()
    for s in seen_news:
        if s["link"] not in seen_links:
            seen_links.add(s["link"])
            final_seen.append(s)

    final_seen = final_seen[-600:]

    # Merge new posted records into existing
    updated_records = posted_records + new_posted_records
    updated_records = updated_records[-30:]  # Keep last 30 records

    return {
        "restructuring_companies": list(set(restructuring_comps)),
        "digests_ru": digests_ru,
        "seen_news": final_seen,
        "posted_news_titles": posted_news_titles,
        "selected_tip_term": selected_tip_term,
        "posted_news_records": updated_records
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
