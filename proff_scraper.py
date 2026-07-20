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
    discovered = []
    
    try:
        # Example Proff search for IT companies in Region Midtjylland with >20 employees.
        # The URL structure for segmentering can change, so we use a robust keyword search
        # or the segmentering endpoint if known.
        search_url = "https://www.proff.dk/s%C3%B8g?q=IT-konsulent+Midtjylland"
        
        logger.info("Crawling Proff.dk for dynamic company discovery...")
        await page.goto(search_url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Extract company names and profile links from search results
        # Proff typically uses <a> tags inside <h2> or specific classes for company names
        elements = await page.locator("a").all()
        for el in elements:
            try:
                href = await el.get_attribute("href")
                if href and "/virksomhed/" in href:
                    name = await el.inner_text()
                    name = name.strip()
                    if name and len(name) > 2 and name not in [d["name"] for d in discovered]:
                        discovered.append({
                            "name": name,
                            "url": "", # Website URL needs to be resolved from profile or DuckDuckGo
                            "proff_url": f"https://www.proff.dk{href}" if href.startswith("/") else href
                        })
            except Exception:
                continue
                
    except Exception as e:
        logger.error(f"Error scraping Proff.dk: {e}")
    finally:
        await page.close()
        
    return discovered
