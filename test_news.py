import asyncio
import os
import json
import news_monitor

async def test():
    # Test RSS directly
    v2_arts = await news_monitor.fetch_rss(news_monitor.RSS_FEEDS["Version2"])
    cw_arts = await news_monitor.fetch_rss(news_monitor.RSS_FEEDS["Computerworld"])
    print(f"V2 articles: {len(v2_arts)}, CW articles: {len(cw_arts)}")
    
    # We won't test Groq unless we have a key, so let's just print the articles:
    if v2_arts:
        print(f"Sample V2: {v2_arts[0]['title']}")
    if cw_arts:
        print(f"Sample CW: {cw_arts[0]['title']}")

if __name__ == "__main__":
    asyncio.run(test())
