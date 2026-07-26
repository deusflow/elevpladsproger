
import asyncio
import time
from datetime import datetime
import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_monitor import process_news, jaccard_similarity

async def main():
    print("Testing Jaccard Similarity:")
    t1 = "Nyt lovforslag vil fjerne AUB-bonus for virksomheder uden lærlinge"
    t2 = "Regeringen vil sløjfe AUB-bonus til virksomheder uden elevpladser"
    sim = jaccard_similarity(t1, t2)
    print(f"Similarity between similar titles: {sim:.2f} (should be > 0.6 if very similar, wait, these words are different, let's see)")

    t3 = "Aarhus Tech åbner ny it-supporter linje"
    t4 = "Aarhus Tech åbner ny it-supporter uddannelse"
    print(f"Similarity between very similar titles: {jaccard_similarity(t3, t4):.2f}")

    # Mock State
    current_time = datetime.now().timestamp()
    state = {
        "seen_news": [
            # 1. Exact link match (recent)
            {"link": "https://example.com/news1", "title": "Old News 1", "timestamp": current_time - 100},
            
            # 2. Semantic match (recent)
            {"link": "https://example.com/news2", "title": "Apple lancerer ny iPhone 16 med AI", "timestamp": current_time - 1000},
            
            # 3. Old exact link (should be purged, >10 days)
            {"link": "https://example.com/news3", "title": "Very Old News", "timestamp": current_time - 11 * 86400},
            
            # 4. Old semantic match (should be purged, >10 days)
            {"link": "https://example.com/news4", "title": "ChatGPT får ny opdatering", "timestamp": current_time - 11 * 86400},
        ]
    }
    
    # Mock config RSS to avoid fetching real stuff
    import config
    config.RSS_FEEDS = {} # Disable real fetching
    
    # We will inject some mock `all_articles` into `news_monitor.py` by overriding it temporarily
    import news_monitor
    
    original_fetch = news_monitor.fetch_rss
    
    async def mock_fetch_rss(url):
        return [
            # Should be blocked by exact link
            {"link": "https://example.com/news1", "title": "Old News 1 Updated", "description": "test", "timestamp": current_time},
            
            # Should be blocked by semantic similarity to news2
            {"link": "https://example.com/news2-diff-url", "title": "Apple udgiver ny iPhone 16 med AI", "description": "test", "timestamp": current_time},
            
            # Should PASS because old news3 was purged!
            {"link": "https://example.com/news3", "title": "Very Old News", "description": "test", "timestamp": current_time},
            
            # Should PASS because old news4 was purged (semantic)!
            {"link": "https://example.com/news4-diff-url", "title": "ChatGPT modtager ny opdatering", "description": "test", "timestamp": current_time},
            
            # Completely new
            {"link": "https://example.com/news5", "title": "Completely new article", "description": "test", "timestamp": current_time}
        ], True

    news_monitor.fetch_rss = mock_fetch_rss
    config.RSS_FEEDS = {"Mock": "http://mock"}
    
    # Override LLM call so we don't actually hit Gemini
    async def mock_ask_llm(batch, target_companies, used_terms, **kwargs):
        return {
            "restructuring_companies": [],
            "digest_ru": "📰 *Test Digest*\n\n📌 *Test*\nThis is a test.\n\n▫️ ▫️ ▫️\n💡 *Term:* Test",
            "used_term": "Test Term"
        }
    news_monitor.ask_llm_news = mock_ask_llm

    print("\nRunning process_news...")
    res = await process_news(state)
    
    print("\nResult seen_news:")
    for s in res["seen_news"]:
        print(f"- {s['link']} | {s['title']} | Age: {(current_time - s['timestamp'])/86400:.1f} days")
        
if __name__ == '__main__':
    asyncio.run(main())
