import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ai_scorer
import news_monitor


class TestAIPipeline(unittest.TestCase):
    def test_active_groq_models(self):
        """Verify deprecated Groq models (llama-3.1-8b-instant, llama-3.3-70b-versatile) are NOT used."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_scorer.py")) as f:
            scorer_code = f.read()
        self.assertNotIn("llama-3.1-8b-instant", scorer_code)
        self.assertNotIn("llama-3.3-70b-versatile", scorer_code)
        self.assertIn("openai/gpt-oss-120b", scorer_code)

        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "news_monitor.py")) as f:
            news_code = f.read()
        self.assertNotIn("llama-3.1-8b-instant", news_code)
        self.assertNotIn("llama-3.3-70b-versatile", news_code)
        self.assertIn("openai/gpt-oss-120b", news_code)
        self.assertIn("openai/gpt-oss-20b", news_code)


if __name__ == "__main__":
    unittest.main()
