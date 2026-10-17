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
        """TARGET_POSTAL_CODES must cover Jutland + Funen and exclude Zealand/Hovedstaden."""
        # Midtjylland
        self.assertIn("8000", config.TARGET_POSTAL_CODES)
        self.assertIn("8800", config.TARGET_POSTAL_CODES)
        self.assertIn("8600", config.TARGET_POSTAL_CODES)
        # Nordjylland
        self.assertIn("9000", config.TARGET_POSTAL_CODES)   # Aalborg
        self.assertIn("9800", config.TARGET_POSTAL_CODES)   # Hjørring
        # Syddanmark (incl. Funen)
        self.assertIn("5000", config.TARGET_POSTAL_CODES)   # Odense
        self.assertIn("6000", config.TARGET_POSTAL_CODES)   # Kolding
        self.assertIn("6700", config.TARGET_POSTAL_CODES)   # Esbjerg
        self.assertIn("7100", config.TARGET_POSTAL_CODES)   # Vejle
        self.assertNotIn("2100", config.TARGET_POSTAL_CODES)  # Copenhagen
        self.assertNotIn("4000", config.TARGET_POSTAL_CODES)  # Roskilde
        self.assertNotIn("3700", config.TARGET_POSTAL_CODES)  # Bornholm

    def test_target_regions(self):
        """Region scope must cover Jutland + Funen with matching URL slugs."""
        self.assertEqual(
            config.TARGET_REGIONS,
            ["Midtjylland", "Nordjylland", "Syddanmark"],
        )
        self.assertEqual(
            config.TARGET_REGION_SLUGS,
            ["region-midtjylland", "region-nordjylland", "region-syddanmark"],
        )
        for slug in config.TARGET_REGION_SLUGS:
            self.assertNotIn(" ", slug)
        # Every region must share its slug prefix
        for region in config.TARGET_REGIONS:
            self.assertTrue(
                any(slug == f"region-{region.lower()}" for slug in config.TARGET_REGION_SLUGS),
                msg=region,
            )

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
