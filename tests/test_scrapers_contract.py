import unittest
import sys
import os
import asyncio
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scrapers
import company_scrapers


class TestScrapersContract(unittest.TestCase):
    def test_scrapers_imports_and_definitions(self):
        """Verify scrapers and company_scrapers have all required dependencies and callable functions."""
        self.assertTrue(callable(scrapers.scrape_thehub))
        self.assertTrue(callable(scrapers.scrape_elevplads))
        self.assertTrue(callable(scrapers.scrape_linkedin))
        self.assertTrue(callable(company_scrapers.try_teamtailor_api))
        self.assertTrue(callable(company_scrapers.extract_jobs_with_groq))

    def test_scrape_thehub_safe_execution(self):
        """scrape_thehub should execute without NameError (httpx must be defined)."""
        class MockResponse:
            status_code = 200
            def json(self):
                return {"docs": []}

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockResponse()):
                jobs = await scrapers.scrape_thehub()
                self.assertIsInstance(jobs, list)
                # Must not contain scraper_error for NameError
                self.assertFalse(any(j.get("type") == "scraper_error" and "httpx" in j.get("error", "") for j in jobs))

        asyncio.run(run_test())

    def test_try_teamtailor_api_safe_execution(self):
        """try_teamtailor_api should execute without NameError."""
        class MockResponse:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self):
                return {"items": []}

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockResponse()):
                jobs = await company_scrapers.try_teamtailor_api("Test Co", "https://example.com/jobs")
                self.assertIsInstance(jobs, list)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
