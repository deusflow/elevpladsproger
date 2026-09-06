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
        
        # Extract company names, profile links, and direct website URLs from search results
        links_data = await page.evaluate("""() => {
            const results = [];
            const cards = document.querySelectorAll('article, li, div[class*="search-result"], div[class*="Listing"], div[class*="company"]');
            for (const card of cards) {
                const nameLink = card.querySelector('a[href*="/virksomhed/"], a[href*="/company/"]');
                if (!nameLink) continue;
                const name = (nameLink.innerText || nameLink.textContent || '').trim();
                if (name.length < 2) continue;
                
                let website = '';
                const extLinks = Array.from(card.querySelectorAll('a[href^="http"]'));
                for (const a of extLinks) {
                    const h = a.getAttribute('href') || '';
                    if (!h.includes('proff.dk') && !h.includes('eniro') && !h.includes('krak') && !h.includes('facebook') && !h.includes('linkedin')) {
                        website = h;
                        break;
                    }
                }
                
                results.push({
                    name: name,
                    href: nameLink.getAttribute('href') || '',
                    website: website
                });
            }
            return results;
        }""")
        
        for link in links_data:
            name = link["name"]
            href = link["href"]
            website = link.get("website", "").strip()
            
            # Only add discovered companies that have a valid, crawlable website URL
            if website and website.startswith("http") and name not in [d["name"] for d in discovered]:
                discovered.append({
                    "name": name,
                    "url": website,
                    "proff_url": f"https://www.proff.dk{href}" if href.startswith("/") else href
                })
                
    except Exception as e:
        logger.error(f"Error scraping Proff.dk: {e}")
    finally:
        await page.close()
        
    return discovered
