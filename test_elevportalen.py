import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to elevportalen search...")
        # Search for IT/data related
        await page.goto("https://www.elevportalen.dk/ledige-elevpladser/?search=it", wait_until="networkidle")
        content = await page.content()
        with open("elevportalen.html", "w") as f:
            f.write(content)
        print("Saved html to elevportalen.html")
        await browser.close()

asyncio.run(run())
