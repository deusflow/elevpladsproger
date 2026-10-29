import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAIPipeline(unittest.TestCase):
    def test_active_groq_models(self):
        """Verify active Groq models are configured according to official Groq docs (without paid Qwen)."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_scorer.py")) as f:
            scorer_code = f.read()
        self.assertIn("llama-3.3-70b-versatile", scorer_code)
        self.assertIn("openai/gpt-oss-120b", scorer_code)
        self.assertIn("openai/gpt-oss-20b", scorer_code)
        self.assertIn("llama-3.1-8b-instant", scorer_code)
        self.assertNotIn("qwen/qwen3.8-27b", scorer_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news_monitor.py")) as f:
            news_code = f.read()
        self.assertIn("llama-3.3-70b-versatile", news_code)
        self.assertIn("openai/gpt-oss-120b", news_code)
        self.assertIn("openai/gpt-oss-20b", news_code)
        self.assertIn("llama-3.1-8b-instant", news_code)
        self.assertNotIn("qwen/qwen3.8-27b", news_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "company_scrapers.py")) as f:
            scrapers_code = f.read()
        self.assertIn("llama-3.3-70b-versatile", scrapers_code)
        self.assertIn("openai/gpt-oss-120b", scrapers_code)
        self.assertIn("openai/gpt-oss-20b", scrapers_code)
        self.assertIn("llama-3.1-8b-instant", scrapers_code)
        self.assertNotIn("qwen/qwen3.8-27b", scrapers_code)

    def test_gemini_api_key_not_in_url_query_params(self):
        """Verify GEMINI_API_KEY is sent via x-goog-api-key header and never in ?key= URL query param."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for fname in ("ai_scorer.py", "news_monitor.py", "company_scrapers.py"):
            with open(os.path.join(root, fname)) as f:
                code = f.read()
            self.assertNotIn("?key=", code, f"Secret key in URL query found in {fname}")
            self.assertIn("x-goog-api-key", code, f"Missing x-goog-api-key header in {fname}")

    def test_active_gemini_models(self):
        """Verify active Gemini 3.8/3.1 models in pipeline."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_scorer.py")) as f:
            scorer_code = f.read()
        self.assertIn("gemini-3.8-flash", scorer_code)
        self.assertIn("gemini-3.1-flash-lite", scorer_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news_monitor.py")) as f:
            news_code = f.read()
        self.assertIn("gemini-3.8-flash", news_code)
        self.assertIn("gemini-3.1-flash-lite", news_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "company_scrapers.py")) as f:
            scrapers_code = f.read()
        self.assertIn("gemini-3.8-flash", scrapers_code)


if __name__ == "__main__":
    unittest.main()

