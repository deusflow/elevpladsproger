import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers import is_valid_job, format_job


class TestJobFiltering(unittest.TestCase):
    def test_geo_bypass(self):
        """Bypass geo should accept jobs from known company pages without postal/city."""
        self.assertTrue(is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=True))
        self.assertTrue(is_valid_job("Software Lærling", "", "LEGO", "", bypass_geo=True))
        self.assertFalse(is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=False))

    def test_midtjylland_postal_codes(self):
        """Valid Midtjylland postals should pass location check."""
        self.assertTrue(is_valid_job("Datatekniker elev", "8000", "Aarhus Tech", "Aarhus"))
        self.assertTrue(is_valid_job("Datatekniker elev", "8600", "Jyske Bank", "Silkeborg"))
        self.assertTrue(is_valid_job("Datatekniker elev", "7400", "Bankdata", "Herning"))
        self.assertTrue(is_valid_job("Datatekniker elev", "8800", "Viborg IT", "Viborg"))

    def test_non_midtjylland_postal_codes(self):
        """Non-Midtjylland postals should be rejected."""
        self.assertFalse(is_valid_job("Datatekniker elev", "2100", "CPH Tech", "København Ø"))
        self.assertFalse(is_valid_job("Datatekniker elev", "5000", "Odense Software", "Odense C"))
        self.assertFalse(is_valid_job("Datatekniker elev", "4000", "Sjælland Data", "Roskilde"))

    def test_enterprise_requires_it_role(self):
        """Target enterprises like Arla must be filtered out for non-IT jobs (dairy, warehouse, sales)."""
        # Non-IT roles at target enterprises must fail
        self.assertFalse(is_valid_job("Mejerist elev", "8260", "Arla Foods", "Viby J"))
        self.assertFalse(is_valid_job("Lager og logistik lærling", "8260", "Arla", "Viby J"))
        
        # IT roles at target enterprises must pass
        self.assertTrue(is_valid_job("Datatekniker elev", "8260", "Arla Foods", "Viby J"))
        self.assertTrue(is_valid_job("Software Developer Trainee", "8260", "Arla", "Viby J"))

    def test_hard_exclusions(self):
        """Pure helpdesk, studentermedhjælper, and unpaid internships should be rejected."""
        self.assertFalse(is_valid_job("Studentermedhjælper til IT", "8000", "Some IT", "Aarhus"))
        self.assertFalse(is_valid_job("Helpdesk supporter elev", "8000", "Support A/S", "Aarhus"))
        self.assertFalse(is_valid_job("IT-supporter elev", "8000", "Support A/S", "Aarhus"))
        self.assertFalse(is_valid_job("Ulønnet praktikant software", "8000", "Startup", "Aarhus"))

    def test_specialized_programming_override(self):
        """Datatekniker with programming specialization should pass."""
        self.assertTrue(is_valid_job("Datatekniker (Infrastruktur og Programmering)", "8000", "Company", "Aarhus"))
        self.assertTrue(is_valid_job("Datatekniker med speciale i programmering", "8000", "Company", "Aarhus"))

    def test_format_job(self):
        """format_job returns expected dictionary schema."""
        job = format_job(
            job_id="test123",
            title="Software Elev",
            company="Test Corp",
            url="https://example.com/job/1",
            source="Jobindex"
        )
        self.assertEqual(job["job_id"], "test123")
        self.assertEqual(job["title"], "Software Elev")
        self.assertEqual(job["company"], "Test Corp")
        self.assertEqual(job["url"], "https://example.com/job/1")
        self.assertEqual(job["source"], "Jobindex")
        self.assertIn("discovered_at", job)


if __name__ == "__main__":
    unittest.main()
