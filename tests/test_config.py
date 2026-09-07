import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class TestConfig(unittest.TestCase):
    def test_news_feeds_structure(self):
        """All configured RSS feeds must have valid HTTP/HTTPS URLs."""
        self.assertGreater(len(config.RSS_FEEDS), 0)
        for name, url in config.RSS_FEEDS.items():
            self.assertIsInstance(name, str)
            self.assertTrue(url.startswith("http://") or url.startswith("https://"))

    def test_postal_ranges(self):
        """TARGET_POSTAL_CODES must cover Region Midtjylland (including 8000 Aarhus, 8800 Viborg)."""
        self.assertIn("8000", config.TARGET_POSTAL_CODES)
        self.assertIn("8800", config.TARGET_POSTAL_CODES)
        self.assertIn("8600", config.TARGET_POSTAL_CODES)
        self.assertNotIn("2100", config.TARGET_POSTAL_CODES)  # Copenhagen

    def test_target_enterprises(self):
        """Target enterprises list should contain key regional enterprise employers."""
        self.assertIn("arla", config.TARGET_ENTERPRISES)
        self.assertIn("eurowind", config.TARGET_ENTERPRISES)
        self.assertIn("thise mejeri", config.TARGET_ENTERPRISES)

    def test_exclusion_pattern(self):
        """Exclusion regex must match unwanted roles."""
        self.assertIsNotNone(config.EXCLUSION_PATTERN.search("helpdesk medarbejder"))
        self.assertIsNotNone(config.EXCLUSION_PATTERN.search("servicedesk"))
        self.assertIsNotNone(config.EXCLUSION_PATTERN.search("it-supporter elev"))
        self.assertIsNotNone(config.EXCLUSION_PATTERN.search("studentermedhjælper"))
        self.assertIsNotNone(config.EXCLUSION_PATTERN.search("internship"))


if __name__ == "__main__":
    unittest.main()
