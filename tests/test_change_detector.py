import unittest
import asyncio
from unittest.mock import patch, AsyncMock
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main
from main import is_relevant_change_link, CHANGE_KEYWORDS


class TestChangeDetector(unittest.TestCase):
    def test_is_relevant_change_link_keywords(self):
        """Test keyword filtering on titles and URLs."""
        # Positive cases: must match relevant IT / apprenticeship keywords
        self.assertTrue(is_relevant_change_link("Datateknikerelev til Region Midtjylland", "https://rm.dk/job/1"))
        self.assertTrue(is_relevant_change_link("Software developer trainee", "https://bankdata.dk/jobs/2"))
        self.assertTrue(is_relevant_change_link("IT-supporter lærling", "https://horsens.dk/job/3"))
        self.assertTrue(is_relevant_change_link("Praktikant i IT og udvikling", "https://au.dk/job/4"))
        self.assertTrue(is_relevant_change_link("Ansøg her", "https://firm.dk/datatekniker-stilling"))
        self.assertTrue(is_relevant_change_link("Elevplads som programmør", "https://lego.com/job/5"))

        # Negative cases: routine municipal / public sector hiring (doctors, nurses, teachers)
        self.assertFalse(is_relevant_change_link("Sygeplejerske til Akutafdelingen", "https://rm.dk/sygeplejerske"))
        self.assertFalse(is_relevant_change_link("Pædagog til Børnehuset Solstrålen", "https://holstebro.dk/paedagog"))
        self.assertFalse(is_relevant_change_link("Lærer til matematik og fysik", "https://horsens.dk/laerer"))
        self.assertFalse(is_relevant_change_link("Social- og sundhedsassistent", "https://lemvig.dk/sosu"))
        self.assertFalse(is_relevant_change_link("Køkkenmedhjælper søges", "https://au.dk/koekken"))
        self.assertFalse(is_relevant_change_link("Overlæge i kardiologi", "https://rm.dk/overlaege"))

    def test_first_run_silent_baseline_migration(self):
        """On first run or migration when company has no snapshot baseline,
        it should silently save snapshot and NOT trigger alerts (0 false alerts).
        """
        initial_state = {
            "jobs": [],
            "company_hashes": {"Horsens Kommune": "hash_123"},
            "company_snapshots": {},  # No snapshot yet
            "_version": 1
        }

        mock_item = {
            "type": "hash",
            "company": "Horsens Kommune",
            "url": "https://horsens.dk/jobs",
            "hash": "new_hash_999",
            "links": [
                {"text": "Datateknikerelev til IT", "url": "https://horsens.dk/it-elev"},
                {"text": "Pædagog", "url": "https://horsens.dk/paedagog"}
            ]
        }

        async def run_test():
            with patch("sys.argv", ["main.py", "--mode", "jobs"]), \
                 patch("main.load_state", new=AsyncMock(return_value=initial_state)), \
                 patch("main.save_state", new=AsyncMock()) as mock_save, \
                 patch("laerepladsen_radar.fetch_laerepladsen_all", new=AsyncMock(return_value=([], []))), \
                 patch("laerepladsen_radar.detect_radar_alerts", return_value=([], {})), \
                 patch("scrapers.scrape_thehub", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_elevplads", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_linkedin", new=AsyncMock(return_value=[])), \
                 patch("main.async_playwright") as mock_pw, \
                 patch("ai_scorer.enrich_jobs_with_ai", new=AsyncMock()), \
                 patch("company_validator.check_accreditation", new=AsyncMock(return_value=True)), \
                 patch("main.notify_telegram", new=AsyncMock()) as mock_notify:

                mock_browser = AsyncMock()
                mock_context = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

                with patch("company_scrapers.scrape_custom_companies", new=AsyncMock(return_value=[mock_item])):
                    await main.main()

                # Verify notify_telegram was NOT called with structural changes
                for call in mock_notify.call_args_list:
                    args, kwargs = call
                    changed_comps = args[1] if len(args) > 1 else kwargs.get("changed_companies", [])
                    self.assertEqual(changed_comps, [], "First run baseline migration must not alert!")

                # Verify state was saved with the new snapshot baseline
                self.assertTrue(mock_save.called)
                saved_state = mock_save.call_args[0][0]
                self.assertIn("Horsens Kommune", saved_state.get("company_snapshots", {}))
                self.assertEqual(len(saved_state["company_snapshots"]["Horsens Kommune"]), 2)

        asyncio.run(run_test())

    def test_non_it_links_changed_ignored_for_telegram(self):
        """When career page adds/changes non-IT links (nurses, educators),
        no Telegram alert should be sent.
        """
        initial_state = {
            "jobs": [],
            "company_hashes": {"Aarhus Universitet": "old_hash"},
            "company_snapshots": {
                "Aarhus Universitet": [
                    {"text": "Lektor i Filosofi", "url": "https://au.dk/stilling/10"}
                ]
            },
            "_version": 1
        }

        # New run has different hash and added a nurse and an educator job
        mock_item = {
            "type": "hash",
            "company": "Aarhus Universitet",
            "url": "https://au.dk/stillinger",
            "hash": "new_hash_modified",
            "links": [
                {"text": "Lektor i Filosofi", "url": "https://au.dk/stilling/10"},
                {"text": "Sygeplejerske til Forskningsklinik", "url": "https://au.dk/stilling/11"},
                {"text": "Pædagog til Børnehus", "url": "https://au.dk/stilling/12"}
            ]
        }

        async def run_test():
            with patch("sys.argv", ["main.py", "--mode", "jobs"]), \
                 patch("main.load_state", new=AsyncMock(return_value=initial_state)), \
                 patch("main.save_state", new=AsyncMock()) as mock_save, \
                 patch("laerepladsen_radar.fetch_laerepladsen_all", new=AsyncMock(return_value=([], []))), \
                 patch("laerepladsen_radar.detect_radar_alerts", return_value=([], {})), \
                 patch("scrapers.scrape_thehub", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_elevplads", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_linkedin", new=AsyncMock(return_value=[])), \
                 patch("main.async_playwright") as mock_pw, \
                 patch("ai_scorer.enrich_jobs_with_ai", new=AsyncMock()), \
                 patch("company_validator.check_accreditation", new=AsyncMock(return_value=True)), \
                 patch("main.notify_telegram", new=AsyncMock()) as mock_notify:

                mock_browser = AsyncMock()
                mock_context = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

                with patch("company_scrapers.scrape_custom_companies", new=AsyncMock(return_value=[mock_item])):
                    await main.main()

                # Verify notify_telegram was NOT called with changed_companies
                for call in mock_notify.call_args_list:
                    args, kwargs = call
                    changed_comps = args[1] if len(args) > 1 else kwargs.get("changed_companies", [])
                    self.assertEqual(changed_comps, [], "Non-IT link changes must NOT trigger Telegram alerts!")

                # Verify snapshot was updated to latest
                self.assertTrue(mock_save.called)
                saved_state = mock_save.call_args[0][0]
                self.assertEqual(len(saved_state["company_snapshots"]["Aarhus Universitet"]), 3)

        asyncio.run(run_test())

    def test_relevant_it_elev_link_triggers_detailed_alert(self):
        """When career page adds a new link matching IT/elev keywords,
        alert should be triggered with company name, specific new link title, and direct link.
        """
        initial_state = {
            "jobs": [],
            "company_hashes": {"Horsens Kommune": "old_hash"},
            "company_snapshots": {
                "Horsens Kommune": [
                    {"text": "Pædagog", "url": "https://horsens.dk/paedagog"}
                ]
            },
            "_version": 1
        }

        mock_item = {
            "type": "hash",
            "company": "Horsens Kommune",
            "url": "https://horsens.dk/stillinger",
            "hash": "new_hash_modified",
            "links": [
                {"text": "Pædagog", "url": "https://horsens.dk/paedagog"},
                {"text": "Datateknikerelev med speciale i programmering", "url": "https://horsens.dk/job/datatekniker-1"}
            ]
        }

        async def run_test():
            with patch("sys.argv", ["main.py", "--mode", "jobs"]), \
                 patch("main.load_state", new=AsyncMock(return_value=initial_state)), \
                 patch("main.save_state", new=AsyncMock()), \
                 patch("laerepladsen_radar.fetch_laerepladsen_all", new=AsyncMock(return_value=([], []))), \
                 patch("laerepladsen_radar.detect_radar_alerts", return_value=([], {})), \
                 patch("scrapers.scrape_thehub", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_elevplads", new=AsyncMock(return_value=[])), \
                 patch("scrapers.scrape_linkedin", new=AsyncMock(return_value=[])), \
                 patch("main.async_playwright") as mock_pw, \
                 patch("ai_scorer.enrich_jobs_with_ai", new=AsyncMock()), \
                 patch("company_validator.check_accreditation", new=AsyncMock(return_value=True)), \
                 patch("main.notify_telegram", new=AsyncMock()) as mock_notify:

                mock_browser = AsyncMock()
                mock_context = AsyncMock()
                mock_browser.new_context.return_value = mock_context
                mock_pw.return_value.__aenter__.return_value.chromium.launch.return_value = mock_browser

                with patch("company_scrapers.scrape_custom_companies", new=AsyncMock(return_value=[mock_item])):
                    await main.main()

                # Verify notify_telegram WAS called with changed_companies
                found_alert = False
                for call in mock_notify.call_args_list:
                    args, kwargs = call
                    changed_comps = args[1] if len(args) > 1 else kwargs.get("changed_companies", [])
                    if changed_comps:
                        found_alert = True
                        self.assertEqual(len(changed_comps), 1)
                        self.assertEqual(changed_comps[0]["company"], "Horsens Kommune")
                        self.assertIn("new_links", changed_comps[0])
                        self.assertEqual(len(changed_comps[0]["new_links"]), 1)
                        self.assertIn("Datateknikerelev", changed_comps[0]["new_links"][0]["text"])
                        self.assertEqual(changed_comps[0]["new_links"][0]["url"], "https://horsens.dk/job/datatekniker-1")

                self.assertTrue(found_alert, "Expected Telegram alert for relevant IT/elev link!")

        asyncio.run(run_test())

    def test_notify_telegram_message_formatting(self):
        """Test that notify_telegram formats changed companies with direct links."""
        changed_companies = [
            {
                "company": "Horsens Kommune",
                "url": "https://horsens.dk/stillinger",
                "new_links": [
                    {
                        "text": "Datateknikerelev i IT-afdelingen",
                        "url": "https://horsens.dk/job/101"
                    }
                ]
            }
        ]

        sent_messages = []
        async def mock_send(client, msg, parse_mode="HTML"):
            sent_messages.append(msg)

        async def run_test():
            with patch("main.config.TELEGRAM_BOT_TOKEN", "mock_token"), \
                 patch("main.config.TELEGRAM_CHAT_ID", "mock_chat"), \
                 patch("main._send_telegram_message", side_effect=mock_send):
                await main.notify_telegram([], changed_companies)

            self.assertEqual(len(sent_messages), 1)
            msg = sent_messages[0]
            self.assertIn("Horsens Kommune", msg)
            self.assertIn("Datateknikerelev i IT-afdelingen", msg)
            self.assertIn("https://horsens.dk/job/101", msg)
            self.assertIn("<a href=\"https://horsens.dk/job/101\">Datateknikerelev i IT-afdelingen</a>", msg)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
