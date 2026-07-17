import asyncio
from playwright.async_api import async_playwright
import json

async def check_url(page, name, url):
    try:
        resp = await page.goto(url, wait_until="networkidle", timeout=15000)
        status = resp.status if resp else "No Response"
        content = await page.content()
        length = len(content)
        print(f"{name}: URL={url} | Status={status} | Length={length}")
        if "404" in content or "not found" in content.lower():
            print(f"  WARNING: Possible 404 or Not Found on page for {name}")
    except Exception as e:
        print(f"{name}: FAILED to load {url} - {e}")

async def main():
    with open("target_companies.json") as f:
        companies = json.load(f)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        for c in companies:
            await check_url(page, c['name'], c['url'])
        await browser.close()

asyncio.run(main())
