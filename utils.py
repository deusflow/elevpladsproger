import json
import logging

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
        text_content = text_content[start:end + 1]
    return json.loads(text_content, strict=False)


import re
import urllib.parse

STOP_WORDS = {
    "og", "i", "til", "på", "for", "med", "af", "at", "en", "et", "den", "det",
    "vores", "hos", "søger", "vi", "som", "ny", "nye", "din", "dit", "stilling",
    "mulig", "om", "eller", "and", "in", "to", "for", "with", "a", "an", "the",
    "our", "seeking", "looking", "we", "are", "team", "afdeling", "ledig", "ledige",
    "opslag", "job"
}

LEGAL_SUFFIXES_PATTERN = re.compile(
    r'\b(?:a/?s|aps|i/?s|p/?s|k/?s|gmbh|ltd|inc|holding|denmark|danmark|group|int(?:ernational)?|kommune|region)\b',
    re.IGNORECASE
)

COMPOUND_SUFFIX_RE = re.compile(r'^(.*)(elev|lærling|apprentice)$', re.IGNORECASE)


def normalize_company_name(name: str) -> str:
    """Normalize Danish and international company names by stripping legal forms, locations, and punctuation."""
    if not name:
        return ""
    name_clean = name.lower()
    # Remove parenthetical expressions like "(Scanrate)" or "(Aarhus)"
    name_clean = re.sub(r'[\(\[\{].*?[\)\]\}]', ' ', name_clean)
    # Strip legal entity suffixes
    name_clean = LEGAL_SUFFIXES_PATTERN.sub(' ', name_clean)
    # Remove punctuation
    name_clean = re.sub(r'[^\w\s]', ' ', name_clean)
    return re.sub(r'\s+', ' ', name_clean).strip()


def extract_title_tokens(title: str) -> set[str]:
    """Tokenize and normalize job titles, expanding Danish compound words (e.g. datateknikerelev -> datatekniker + elev)."""
    if not title:
        return set()
    cleaned = re.sub(r'[^\w\s]', ' ', title.lower())
    raw_tokens = cleaned.split()
    tokens = set()
    for t in raw_tokens:
        if len(t) <= 1 or t in STOP_WORDS:
            continue
        tokens.add(t)
        # Expand Danish compound apprentice words
        m = COMPOUND_SUFFIX_RE.match(t)
        if m and len(m.group(1)) >= 3:
            stem = m.group(1).rstrip("-")
            suffix = m.group(2)
            tokens.add(stem)
            tokens.add(suffix)
    return tokens


def normalize_job_url(url: str) -> str:
    """Strip tracking and ephemeral query parameters to obtain canonical job URL."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        query_dict = urllib.parse.parse_qs(parsed.query)
        # Retain significant query params like 'job=' or 'id=' if needed, but strip utm/tracking
        filtered_query = {k: v for k, v in query_dict.items() if k.lower() in ("job", "id", "jobadid", "jobid")}
        new_query = urllib.parse.urlencode(filtered_query, doseq=True)
        canonical = urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            new_query,
            ""
        ))
        return canonical
    except Exception:
        return url.strip()


def are_jobs_duplicate(job1: dict, job2: dict) -> bool:
    """Intelligently determine whether two job records represent the same opportunity.
    Handles cross-portal naming variations (e.g., Jobindex vs Jobnet vs Lærepladsen)
    while preserving genuinely distinct positions (e.g., Programming vs Infrastructure).
    """
    # 1. Exact canonical URL match
    url1 = normalize_job_url(job1.get("url", ""))
    url2 = normalize_job_url(job2.get("url", ""))
    if url1 and url2 and url1 == url2:
        return True

    # 2. Company comparison
    c1 = normalize_company_name(job1.get("company", ""))
    c2 = normalize_company_name(job2.get("company", ""))
    if not c1 or not c2:
        return False

    # Check company match (exact or one contains the other, e.g. "lego" and "lego group")
    company_match = (c1 == c2) or (c1 in c2) or (c2 in c1)
    if not company_match:
        return False

    # 3. Title comparison
    t1_raw = (job1.get("title") or "").strip().lower()
    t2_raw = (job2.get("title") or "").strip().lower()
    if t1_raw and t2_raw and t1_raw == t2_raw:
        return True

    tokens1 = extract_title_tokens(t1_raw)
    tokens2 = extract_title_tokens(t2_raw)
    if not tokens1 or not tokens2:
        return False

    # 4. Specialization conflict check:
    # If one role is explicitly programming/software and the other is infrastructure/server/network,
    # they are different educational specialties under Datatekniker (5.5 yrs) -> DO NOT merge!
    prog_keys = {"programmering", "software", "udvikler", "developer", "kodning", "data"}
    infra_keys = {"infrastruktur", "infrastructure", "netværk", "server", "drift"}

    has_prog1 = bool(tokens1 & prog_keys)
    has_infra1 = bool(tokens1 & infra_keys)
    has_prog2 = bool(tokens2 & prog_keys)
    has_infra2 = bool(tokens2 & infra_keys)

    if (has_prog1 and not has_infra1 and has_infra2 and not has_prog2) or \
       (has_infra1 and not has_prog1 and has_prog2 and not has_infra2):
        return False

    # 5. Jaccard similarity of significant tokens
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    similarity = intersection / union if union else 0.0

    return similarity >= 0.55

