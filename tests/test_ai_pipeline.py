import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAIPipeline(unittest.TestCase):
    def test_active_groq_models(self):
        """Verify non-existent models are removed and active Groq models are configured."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_scorer.py")) as f:
            scorer_code = f.read()
        self.assertNotIn("openai/gpt-oss-120b", scorer_code)
        self.assertNotIn("openai/gpt-oss-20b", scorer_code)
        self.assertIn("llama-3.3-70b-versatile", scorer_code)
        self.assertIn("llama-3.1-8b-instant", scorer_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news_monitor.py")) as f:
            news_code = f.read()
        self.assertNotIn("openai/gpt-oss-120b", news_code)
        self.assertNotIn("openai/gpt-oss-20b", news_code)
        self.assertIn("llama-3.3-70b-versatile", news_code)
        self.assertIn("llama-3.1-8b-instant", news_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "company_scrapers.py")) as f:
            scrapers_code = f.read()
        self.assertNotIn("openai/gpt-oss-20b", scrapers_code)
        self.assertIn("llama-3.3-70b-versatile", scrapers_code)

    def test_active_gemini_models(self):
        """Verify active Gemini models in pipeline and absence of ghost models."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_scorer.py")) as f:
            scorer_code = f.read()
        self.assertNotIn("gemini-3.8-flash", scorer_code)
        self.assertNotIn("gemini-3.1-flash-lite", scorer_code)
        self.assertIn("gemini-2.5-flash-lite", scorer_code)
        self.assertIn("gemini-2.0-flash", scorer_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news_monitor.py")) as f:
            news_code = f.read()
        self.assertNotIn("gemini-3.8-flash", news_code)
        self.assertNotIn("gemini-3.1-flash-lite", news_code)
        self.assertIn("gemini-2.5-flash", news_code)
        self.assertIn("gemini-2.5-flash-lite", news_code)


if __name__ == "__main__":
    unittest.main()

