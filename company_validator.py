import asyncio
import json
import logging
import os
import time
import urllib.parse
from typing import Optional

import httpx

import config

logger = logging.getLogger("elevplads_scraper")

# In-memory cache for validated companies
VALIDATION_CACHE: dict[str, bool] = {}
_cvr_lock = asyncio.Lock()
_last_cvr_call_ts: float = 0.0

# Pre-compiled whitelist of Danish public and institutional entities
PUBLIC_SECTOR_PATTERNS = (
    "kommune", "region ", "universitet", "hospital", "ministerie",
    "politi", "forsvar", "statsforvaltning", "styrelse", "skoleoplæring", "mercantec"
)

_KNOWN_TARGET_COMPANIES: Optional[set[str]] = None


def _get_known_target_companies() -> set[str]:
    global _KNOWN_TARGET_COMPANIES
    if _KNOWN_TARGET_COMPANIES is not None:
        return _KNOWN_TARGET_COMPANIES

    companies = set()
    try:
        target_path = os.path.join(os.path.dirname(__file__), "target_companies.json")
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    if isinstance(item, dict) and item.get("name"):
                        companies.add(item["name"].lower().strip())
    except Exception as e:
        logger.warning(f"Could not load target_companies.json for CVR whitelist: {e}")

    # Also add config.TARGET_ENTERPRISES
    for enterprise in getattr(config, "TARGET_ENTERPRISES", []):
        companies.add(enterprise.lower().strip())

    _KNOWN_TARGET_COMPANIES = companies
    return _KNOWN_TARGET_COMPANIES


def set_validation_cache(cache: dict[str, bool]) -> None:
    """Load persistent CVR cache from state."""
    global VALIDATION_CACHE
    if isinstance(cache, dict):
        VALIDATION_CACHE.update(cache)


def get_validation_cache() -> dict[str, bool]:
    """Retrieve current CVR validation cache."""
    return VALIDATION_CACHE.copy()


def is_known_approved_company(company_name: str) -> bool:
    """Checks if company is a verified target employer or public entity without network calls."""
    normalized = company_name.lower().strip()
    known = _get_known_target_companies()
    if normalized in known:
        return True
    if any(pattern in normalized for pattern in PUBLIC_SECTOR_PATTERNS):
        return True
    return False


async def check_accreditation(company_name: str) -> bool:
    """
    Checks if a company is a valid IT business or recognized employer via CVR API.
    Returns True if valid IT company, False if not (or unknown).
    Includes rate-limiting, whitelist checking, and persistent caching.
    """
    global _last_cvr_call_ts

    if not company_name or not company_name.strip():
        return False

    normalized = company_name.lower().strip()

    # 1. Check in-memory / persistent cache
    if normalized in VALIDATION_CACHE:
        return VALIDATION_CACHE[normalized]

    # 2. Check whitelist (target companies, municipalities, universities)
    if is_known_approved_company(normalized):
        VALIDATION_CACHE[normalized] = True
        return True

    # 3. Query external cvrapi.dk with rate-limiting and lock
    async with _cvr_lock:
        # Re-check cache after acquiring lock
        if normalized in VALIDATION_CACHE:
            return VALIDATION_CACHE[normalized]

        # Rate-limiting throttle: minimum 1.5s between outbound calls to cvrapi.dk
        elapsed = time.time() - _last_cvr_call_ts
        if elapsed < 1.5:
            await asyncio.sleep(1.5 - elapsed)

        headers = {"User-Agent": "Elevpladsproger/1.0 (deusflow@proton.me)"}
        cvr_token = os.getenv("CVR_API_KEY") or os.getenv("CVR_TOKEN")
        if cvr_token:
            headers["Authorization"] = f"Bearer {cvr_token}"

        search_url = f"https://cvrapi.dk/api?search={urllib.parse.quote(company_name)}&country=dk"

        for attempt in range(1, 3):
            try:
                _last_cvr_call_ts = time.time()
                async with httpx.AsyncClient() as client:
                    response = await client.get(search_url, headers=headers, timeout=10.0)

                    if response.status_code == 200:
                        data = response.json()
                        if not data.get("error"):
                            industry_code = data.get("industrycode", 0)
                            # IT industry code starts with 62, or large company with >10 employees
                            is_approved = str(industry_code).startswith("62") or data.get("employees", 0) > 10
                            VALIDATION_CACHE[normalized] = is_approved
                            return is_approved
                        else:
                            # Explicit error from CVR (e.g. company not found)
                            VALIDATION_CACHE[normalized] = False
                            return False

                    elif response.status_code == 429:
                        logger.warning(f"cvrapi.dk rate limited (429) on {company_name} (attempt {attempt}/2). Waiting 3s...")
                        await asyncio.sleep(3.0)
                    else:
                        logger.warning(f"cvrapi.dk returned status {response.status_code} for {company_name}")
                        break

            except Exception as e:
                logger.error(f"Error checking accreditation for {company_name} (attempt {attempt}/2): {e}")
                await asyncio.sleep(1.5)

    # Note: On transient error/timeout/rate-limit, DO NOT store False in cache so it can be retried cleanly next time
    return False

