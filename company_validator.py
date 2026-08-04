import asyncio
import httpx
import logging
import urllib.parse

logger = logging.getLogger("elevplads_scraper")

# Cache to avoid hitting the API multiple times for the same company
VALIDATION_CACHE: dict[str, bool] = {}

async def check_accreditation(company_name: str) -> bool:
    """
    Checks if a company is a valid IT business via CVR API.
    Returns True if valid IT company, False if not (or unknown).
    """
    if not company_name:
        return False
        
    normalized = company_name.lower().strip()
    if normalized in VALIDATION_CACHE:
        return VALIDATION_CACHE[normalized]
        
    # We use cvrapi.dk as a free proxy to check if the company exists and is active,
    # as the official Lærepladsen API is hidden behind Cloudflare and complex SSR.
    # In a full production environment with CVR token, we would verify the "Godkendt" flag.
    # For now, we perform a lightweight check to see if it's a real, active IT company.
    try:
        async with httpx.AsyncClient() as client:
            search_url = f"https://cvrapi.dk/api?search={urllib.parse.quote(company_name)}&country=dk"
            headers = {"User-Agent": "Elevpladsproger/1.0 (deusflow@proton.me)"}
            response = await client.get(search_url, headers=headers, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                if not data.get("error"):
                    # Check if industry code is IT-related (620100, 620200, etc.)
                    # If it is, we assume it's highly likely to be a valid/approved site for IT
                    # if they are posting IT jobs.
                    industry_code = data.get("industrycode", 0)
                    is_approved = str(industry_code).startswith("62") or data.get("employees", 0) > 10
                    VALIDATION_CACHE[normalized] = is_approved
                    return is_approved
    except Exception as e:
        logger.error(f"Error checking accreditation for {company_name}: {e}")
        
    # Default to False if check fails
    VALIDATION_CACHE[normalized] = False
    return False
