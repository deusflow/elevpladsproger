import asyncio
from playwright.async_api import async_playwright
import re

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://www.elevportalen.dk/ledige-elevpladser/?search=it", wait_until="networkidle")
        content = await page.content()
        links = set(re.findall(r'href="(/ledige-elevpladser/[^"]+)"', content, re.IGNORECASE))
        print(f"Found {len(links)} links")
        for l in list(links)[:10]:
            print(l)
        await browser.close()

asyncio.run(run())
