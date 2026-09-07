import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from patchright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        async def handle_response(response):
            if "api/soeg-opslag" in response.url:
                print(f"Intercepted API Call: {response.url}")
                
        page.on("response", handle_response)
        
        # Original:
        # https://sr.laerepladsen.dk/soeg-opslag/0/Data-%20og%20kommunikationsuddannelsen/3607/Datatekniker/8871/midtjylland
        # Broad:
        broad_url = "https://sr.laerepladsen.dk/soeg-opslag/0/Data-%20og%20kommunikationsuddannelsen/3607/midtjylland"
        print("Testing broad URL...")
        await page.goto(broad_url)
        await page.wait_for_timeout(3000)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
