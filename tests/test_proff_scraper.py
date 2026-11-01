import unittest
from unittest.mock import AsyncMock, MagicMock
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import proff_scraper


class TestProffScraper(unittest.TestCase):
    def test_discover_it_companies_all_regions(self):
        """discover_it_companies must search all target regions and return deduplicated companies."""
        visited_urls = []

        mock_page = AsyncMock()
        async def fake_goto(url, **kwargs):
            visited_urls.append(url)
            return None

        mock_page.goto = AsyncMock(side_effect=fake_goto)
        mock_page.wait_for_timeout = AsyncMock()

        # Mock evaluate return per call
        evaluate_calls = 0
        async def fake_evaluate(js_code):
            nonlocal evaluate_calls
            evaluate_calls += 1
            if evaluate_calls == 1:
                # Region Midtjylland results
                return [
                    {"name": "Aarhus Software A/S", "href": "/virksomhed/aarhus-software/1", "website": "https://aarhussoftware.dk"},
                    {"name": "Duplicate Tech", "href": "/virksomhed/dup-tech/2", "website": "https://duptech.dk"}
                ]
            elif evaluate_calls == 2:
                # Region Nordjylland results (contains Duplicate Tech again)
                return [
                    {"name": "Aalborg Cloud ApS", "href": "/virksomhed/aalborg-cloud/3", "website": "https://aalborgcloud.dk"},
                    {"name": "Duplicate Tech", "href": "/virksomhed/dup-tech/2", "website": "https://duptech.dk"}
                ]
            else:
                # Region Syddanmark results
                return [
                    {"name": "Odense Robotics IT", "href": "/virksomhed/odense-robotics/4", "website": "https://odenseroboticsit.dk"},
                    {"name": "No Website Firm", "href": "/virksomhed/no-web/5", "website": ""}
                ]

        mock_page.evaluate = AsyncMock(side_effect=fake_evaluate)
        mock_page.close = AsyncMock()

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        async def run_test():
            comps = await proff_scraper.discover_it_companies(mock_context, regions=["Midtjylland", "Nordjylland", "Syddanmark"])

            # 1. Check all 3 regions were visited
            self.assertEqual(len(visited_urls), 3)
            self.assertIn("IT-konsulent+Midtjylland", visited_urls[0])
            self.assertIn("IT-konsulent+Nordjylland", visited_urls[1])
            self.assertIn("IT-konsulent+Syddanmark", visited_urls[2])

            # 2. Check deduplication (Duplicate Tech should only appear once)
            names = [c["name"] for c in comps]
            self.assertEqual(len(names), 4)
            self.assertIn("Aarhus Software A/S", names)
            self.assertIn("Duplicate Tech", names)
            self.assertIn("Aalborg Cloud ApS", names)
            self.assertIn("Odense Robotics IT", names)
            self.assertNotIn("No Website Firm", names)

            # 3. Check region tags
            c_dict = {c["name"]: c for c in comps}
            self.assertEqual(c_dict["Aarhus Software A/S"]["region"], "Midtjylland")
            self.assertEqual(c_dict["Aalborg Cloud ApS"]["region"], "Nordjylland")
            self.assertEqual(c_dict["Odense Robotics IT"]["region"], "Syddanmark")

            # 4. Verify page was closed
            mock_page.close.assert_awaited_once()

        asyncio.run(run_test())

    def test_discover_it_companies_error_resilience(self):
        """If one region encounters a timeout or error, other regions should still be scraped."""
        mock_page = AsyncMock()
        visited = []

        async def fake_goto(url, **kwargs):
            visited.append(url)
            if "Nordjylland" in url:
                raise RuntimeError("Simulated timeout on Nordjylland")
            return None

        mock_page.goto = AsyncMock(side_effect=fake_goto)
        mock_page.wait_for_timeout = AsyncMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {"name": "Resilient IT ApS", "href": "/virksomhed/resilient/1", "website": "https://resilient.dk"}
        ])
        mock_page.close = AsyncMock()

        mock_context = MagicMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        async def run_test():
            comps = await proff_scraper.discover_it_companies(mock_context, regions=["Midtjylland", "Nordjylland", "Syddanmark"])
            self.assertEqual(len(visited), 3)
            self.assertEqual(len(comps), 1)
            self.assertEqual(comps[0]["name"], "Resilient IT ApS")
            mock_page.close.assert_awaited_once()

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()

