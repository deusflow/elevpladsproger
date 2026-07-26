import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_monitor import build_quality_fallback_digest, validate_format, extract_json_payload

def test_fallback():
    mock_batch = [{
        "title": "Nyt lovforslag vil fjerne AUB-bonus for virksomheder uden lærlinge",
        "link": "https://version2.dk/artikel/123",
        "description": "Regeringen vil sløjfe AUB-bonus til virksomheder uden elevpladser for at presse flere it-virksomheder til at tage lærlinge."
    }]
    
    digest = build_quality_fallback_digest(mock_batch, "REST API")
    print("--- GENERATED FALLBACK DIGEST ---")
    print(digest)
    print("--------------------------------")
    
    assert validate_format(digest), "Fallback digest failed format validation!"
    print("Fallback format validation: PASSED!")

def test_json_extractor():
    sample_json_text = """```json
    {
        "restructuring_companies": [],
        "digest_ru": "📰 *Test*\n\n📌 *Что произошло:*\nTest\n\n🔗 [Читать](http://example.com)",
        "used_term": "REST"
    }
    ```"""
    parsed = extract_json_payload(sample_json_text)
    assert parsed["used_term"] == "REST"
    print("JSON extractor test: PASSED!")

if __name__ == "__main__":
    test_fallback()
    test_json_extractor()
