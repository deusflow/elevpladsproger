import asyncio
from patchright.async_api import async_playwright
import proff_scraper

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        comps = await proff_scraper.discover_it_companies(context)
        print("Found:", comps)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
