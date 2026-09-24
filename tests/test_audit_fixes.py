import unittest
import sys
import os
import datetime
from unittest.mock import patch, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils import extract_json_payload
from scrapers import is_valid_job
from cycle_predictor import analyze_and_predict
from main import is_company_in_restructuring


class TestAuditFixes(unittest.TestCase):
    def test_bug2_ai_scorer_empty_fallback(self):
        """BUG-2: ai_scorer.get_match_score must return {} (dict) when no API keys are set."""
        import ai_scorer
        with patch.object(config, "GEMINI_API_KEY", None), patch.object(config, "GROQ_API_KEY", None):
            import asyncio
            result = asyncio.run(ai_scorer.get_match_score("Datatekniker", "Firma", "Jobtekst"))
            self.assertIsInstance(result, dict)
            self.assertEqual(result, {})

    def test_bug7_intern_in_danish_not_excluded(self):
        """BUG-7: Danish word 'intern' (internal) in job title must NOT be excluded."""
        # 'intern' is used in Danish as 'internal IT'
        self.assertTrue(is_valid_job("Datateknikerelev til intern IT", "8000", "Aarhus Kommune", "Aarhus"))
        self.assertTrue(is_valid_job("Datatekniker lærling - intern service", "8800", "Mercantec", "Viborg"))

        # Pure unpaid internships or foreign internships should still be excluded
        self.assertFalse(is_valid_job("Software internship", "8000", "Startup", "Aarhus"))
        self.assertFalse(is_valid_job("Ulønnet praktikant i IT", "8000", "Startup", "Aarhus"))

    def test_bug9_target_companies_path_absolute(self):
        """BUG-9: config.TARGET_COMPANIES_PATH must exist and be an absolute path."""
        self.assertTrue(os.path.isabs(config.TARGET_COMPANIES_PATH))
        self.assertTrue(os.path.exists(config.TARGET_COMPANIES_PATH))

    def test_bug11_techjob_url_schema(self):
        """BUG-11: TechJob search URL must use /sog?query= instead of /search?q=."""
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scrapers.py")) as f:
            content = f.read()
        self.assertIn("https://techjob.dk/sog?query=", content)
        self.assertNotIn("https://techjob.dk/search?q=", content)

    def test_bug12_extract_json_payload_utility(self):
        """BUG-12: extract_json_payload correctly parses raw and markdown-fenced JSON."""
        raw_json = '{"score": 95, "city": "Aarhus"}'
        fenced_json = '```json\n{"score": 95, "city": "Aarhus"}\n```'
        self.assertEqual(extract_json_payload(raw_json), {"score": 95, "city": "Aarhus"})
        self.assertEqual(extract_json_payload(fenced_json), {"score": 95, "city": "Aarhus"})

    def test_bug14_restructuring_fuzzy_match(self):
        """BUG-14: is_company_in_restructuring must match base company names across Danish suffixes."""
        restructuring = ["Microsoft", "Intel", "Danfoss", "Vestas"]
        self.assertTrue(is_company_in_restructuring("Microsoft Danmark ApS", restructuring))
        self.assertTrue(is_company_in_restructuring("Vestas Wind Systems A/S", restructuring))
        self.assertTrue(is_company_in_restructuring("Danfoss Group", restructuring))
        self.assertFalse(is_company_in_restructuring("Salling Group", restructuring))
        self.assertFalse(is_company_in_restructuring("Unknown Tech ApS", restructuring))

    def test_bug15_cycle_predictor_historical_jobs(self):
        """BUG-15: cycle_predictor analyzes historical jobs from previous years."""
        now = datetime.datetime.now(datetime.timezone.utc)
        target_month = now.month + 1 if now.month < 12 else 1
        previous_year = now.year - 1

        mock_state = {
            "predictions_sent": {},
            "jobs": [
                {
                    "company": "KvalitetsCode ApS",
                    "title": "Datatekniker elev",
                    "discovered_at": f"{previous_year}-{target_month:02d}-15T10:00:00+00:00"
                }
            ]
        }
        alerts = analyze_and_predict(mock_state)
        # Should alert on KvalitetsCode ApS because it posted in target_month last year
        self.assertTrue(any("KvalitetsCode ApS" in alert for alert in alerts))
        self.assertTrue(any("Historisk data" in alert for alert in alerts))


if __name__ == "__main__":
    unittest.main()
