import unittest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main


class TestBugLostJobs(unittest.TestCase):
    def test_new_jobs_lost_when_changed_companies_exist(self):
        """Proof of bug in main.py:786-789.
        When new_jobs AND changed_companies both exist,
        the elif branch triggers and passes jobs=[] to notify_telegram,
        causing new_jobs to be completely lost!
        """
        initial_state = {
            "jobs": [],
            "company_hashes": {"Horsens Kommune": "old_hash_123"},
            "company_snapshots": {"Horsens Kommune": [{"text": "Gammel stilling", "url": "https://portal.signatur.dk/old"}]},
            "_version": 1
        }

        mock_job = {
            "job_id": "test_lego_elev_1",
            "title": "Datateknikerelev med speciale i programmering",
            "company": "LEGO Group",
            "url": "https://lego.com/job/1",
            "status": "active"
        }

        mock_hash_change = {
            "type": "hash",
            "company": "Horsens Kommune",
            "url": "https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?clientid=2289",
            "hash": "new_hash_456",
            "links": [
                {"text": "Gammel stilling", "url": "https://portal.signatur.dk/old"},
                {"text": "Datateknikerelev i Horsens", "url": "https://portal.signatur.dk/job/datatekniker"}
            ],
            "llm_verified": False
        }

        async def run_test():
            # Mock CLI args
            with patch("sys.argv", ["main.py", "--mode", "jobs"]), \
                 patch("main.load_state", new=AsyncMock(return_value=initial_state)), \
                 patch("main.save_state", new=AsyncMock()), \
                 patch("laerepladsen_radar.fetch_laerepladsen_all", new=AsyncMock(return_value=([mock_job], []))), \
                 patch("laerepladsen_radar.detect_radar_alerts", return_value=([], {})), \
                 patch("scrapers.scrape_thehub", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_elevplads", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_linkedin", new=AsyncMock(return_value=[])), \
                 patch("main.async_playwright") as mock_pw, \
                 patch("ai_scorer.enrich_jobs_with_ai", new=AsyncMock()), \
                 patch("company_validator.check_accreditation", new=AsyncMock(return_value=True)), \
                 patch("main.notify_telegram", new=AsyncMock()) as mock_notify:

                # Setup playwright mock returning mock_hash_change
                mock_browser = AsyncMock()
                mock_context = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

                with patch("company_scrapers.scrape_custom_companies", new=AsyncMock(return_value=[mock_hash_change])):
                    await main.main()

                # Verify notify_telegram was called
                self.assertTrue(mock_notify.called, "notify_telegram should have been called")

                # Check what jobs were sent:
                # In buggy code: notify_telegram was called with jobs=[] because changed_companies was truthy!
                sent_jobs = []
                for call in mock_notify.call_args_list:
                    args, kwargs = call
                    if args and len(args) > 0:
                        sent_jobs.extend(args[0])

                # BUG PROOF: If the bug is present, sent_jobs is empty and this assertion FAILS!
                self.assertGreater(
                    len(sent_jobs),
                    0,
                    f"BUG DETECTED: mock_job was discovered but sent_jobs is empty ({sent_jobs}) because changed_companies wiped it!"
                )
                self.assertEqual(sent_jobs[0]["job_id"], "test_lego_elev_1")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
