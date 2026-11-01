import logging
import urllib.parse
from typing import Any, Optional
try:
    from playwright_stealth import stealth_async  # type: ignore
except ImportError:
    async def stealth_async(page): pass
try:
    from patchright.async_api import BrowserContext  # type: ignore
except ImportError:
    try:
        from playwright.async_api import BrowserContext  # type: ignore
    except ImportError:
        BrowserContext = Any  # type: ignore

import config

logger = logging.getLogger("elevplads_scraper")

async def discover_it_companies(context: BrowserContext, regions: Optional[list[str]] = None) -> list[dict]:
    """
    Scrapes Proff.dk for IT companies across target regions (Midtjylland, Nordjylland, Syddanmark).
    Uses Playwright + Stealth to bypass DataDome/Cloudflare.
    """
    target_regions = regions or getattr(config, "TARGET_REGIONS", ["Midtjylland", "Nordjylland", "Syddanmark"])
    discovered: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    page = await context.new_page()
    await stealth_async(page)
    try:
        for region in target_regions:
            try:
                q = urllib.parse.quote_plus(f"IT-konsulent {region}")
                search_url = f"https://www.proff.dk/s%C3%B8g?q={q}"

                logger.info(f"Crawling Proff.dk for dynamic company discovery in {region}...")
                await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(2000)

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

                region_count = 0
                for link in links_data:
                    name = link["name"]
                    href = link["href"]
                    website = link.get("website", "").strip()
                    name_clean = name.strip().lower()

                    # Only add discovered companies that have a valid, crawlable website URL
                    if website and website.startswith("http") and name_clean not in seen_names:
                        seen_names.add(name_clean)
                        discovered.append({
                            "name": name,
                            "url": website,
                            "region": region,
                            "proff_url": f"https://www.proff.dk{href}" if href.startswith("/") else href
                        })
                        region_count += 1

                logger.info(f"Proff.dk discovered {region_count} new IT companies in {region}.")
            except Exception as re_err:
                logger.warning(f"Error scraping Proff.dk for region '{region}': {re_err}")
                continue
    except Exception as e:
        logger.error(f"Error in Proff.dk discovery: {e}")
    finally:
        await page.close()

    logger.info(f"Proff.dk dynamic discovery finished. Found {len(discovered)} total companies across {target_regions}.")
    return discovered
