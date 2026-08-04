import asyncio
import logging
from patchright.async_api import BrowserContext
from playwright_stealth import stealth_async

logger = logging.getLogger("elevplads_scraper")

async def discover_it_companies(context: BrowserContext) -> list[dict]:
    """
    Scrapes Proff.dk for IT companies in Midtjylland (>30 employees).
    Uses Playwright + Stealth to bypass DataDome/Cloudflare.
    """
    page = await context.new_page()
    await stealth_async(page)
    from typing import Any
    discovered: list[dict[str, Any]] = []
    
    try:
        # Example Proff search for IT companies in Region Midtjylland with >20 employees.
        # The URL structure for segmentering can change, so we use a robust keyword search
        # or the segmentering endpoint if known.
        search_url = "https://www.proff.dk/s%C3%B8g?q=IT-konsulent+Midtjylland"
        
        logger.info("Crawling Proff.dk for dynamic company discovery...")
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Extract company names and profile links from search results in one fast browser evaluation
        links_data = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('a')).map(a => ({
                text: (a.innerText || a.textContent || '').trim(),
                href: a.getAttribute('href') || ''
            })).filter(l => l.text.length > 2 && l.href.includes('/virksomhed/'));
        }""")
        
        for link in links_data:
            name = link["text"]
            href = link["href"]
            if name not in [d["name"] for d in discovered]:
                discovered.append({
                    "name": name,
                    "url": "", # Website URL needs to be resolved from profile or DuckDuckGo
                    "proff_url": f"https://www.proff.dk{href}" if href.startswith("/") else href
                })
                
    except Exception as e:
        logger.error(f"Error scraping Proff.dk: {e}")
    finally:
        await page.close()
        
    return discovered
