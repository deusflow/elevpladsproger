import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers import is_valid_job, format_job, job_priority


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

    def test_non_target_postal_codes(self):
        """Postals outside Jutland + Funen (Zealand, Hovedstaden) should be rejected."""
        self.assertFalse(is_valid_job("Datatekniker elev", "2100", "CPH Tech", "København Ø"))
        self.assertFalse(is_valid_job("Datatekniker elev", "4000", "Sjælland Data", "Roskilde"))
        self.assertFalse(is_valid_job("Datatekniker elev", "3700", "Bornholm IT", "Rønne"))

    def test_expanded_region_postal_codes(self):
        """Region expansion: Nordjylland and Syddanmark (incl. Funen) are now in scope."""
        # Nordjylland
        self.assertTrue(is_valid_job("Datatekniker elev", "9000", "Aalborg IT", "Aalborg"))
        self.assertTrue(is_valid_job("Datatekniker elev", "9800", "Nord Data", "Hjørring"))
        # Syddanmark — Funen
        self.assertTrue(is_valid_job("Datatekniker elev", "5000", "Odense Software", "Odense C"))
        self.assertTrue(is_valid_job("Datatekniker elev", "5700", "Svendborg IT", "Svendborg"))
        # Syddanmark — Southern Jutland
        self.assertTrue(is_valid_job("Datatekniker elev", "6000", "Kolding Data", "Kolding"))
        self.assertTrue(is_valid_job("Datatekniker elev", "6700", "Esbjerg Tech", "Esbjerg"))
        self.assertTrue(is_valid_job("Datatekniker elev", "7100", "Vejle IT", "Vejle"))

    def test_non_target_region_words_still_excluded(self):
        """Copenhagen/Zealand/Bornholm wording must still be rejected; Funen is accepted."""
        self.assertFalse(is_valid_job("Datatekniker elev", "", "CPH Tech", "København"))
        self.assertFalse(is_valid_job("Datatekniker elev", "", "Sjælland Data", "Roskilde"))
        self.assertFalse(is_valid_job("Datatekniker elev", "", "Bornholm Data", "Rønne"))
        # Funen wording must NOT be rejected anymore
        self.assertTrue(is_valid_job("Datatekniker elev", "", "Odense Software", "Fyn", trusted_region=True))
        self.assertTrue(is_valid_job("Datatekniker elev", "", "Aalborg IT", "Nordjylland", trusted_region=True))

    def test_trusted_region_for_scoped_searches(self):
        """Region-scoped searches (Jobindex/IT-Jobbank) may return small towns without a
        postal code or a known city name; those must be kept, while explicit
        non-Midtjylland locations must still be rejected."""
        # Small Midtjylland town, no postal, unknown to our city list -> kept
        self.assertTrue(is_valid_job("Datatekniker elev", "", "Lokal Virksomhed", "Kolind", trusted_region=True))
        # Explicit Copenhagen location must still be rejected even when trusted
        self.assertFalse(is_valid_job("Datatekniker elev", "", "CPH Tech", "København", trusted_region=True))
        # Without the trusted flag the inconclusive location is dropped
        self.assertFalse(is_valid_job("Datatekniker elev", "", "Lokal Virksomhed", "Kolind"))

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

    def test_it_support_variants_excluded(self):
        """Core requirement: all pure IT-support/helpdesk variants must be excluded."""
        titles = [
            "IT-support elev",
            "It-support elev",
            "IT support elev",
            "IT-supporter elev",
            "Supporter elev",
            "Helpdesk elev",
            "Servicedesk elev",
            "Lærling til IT-drift og support",
            "IT-elev til support og drift",
            "CIMBRIA SØGER IT-SUPPORTER ELEV",
        ]
        for title in titles:
            self.assertFalse(is_valid_job(title, "8000", "Firma", "Aarhus"), msg=title)

    def test_support_with_dev_signal_is_kept(self):
        """A support-flavoured title that clearly involves programming must survive."""
        self.assertTrue(is_valid_job("Elev til IT-support og softwareudvikling", "8000", "Firma", "Aarhus"))
        self.assertTrue(is_valid_job("Datatekniker med speciale i programmering og support", "8000", "Firma", "Aarhus"))

    def test_non_it_titles_with_tech_word_rejected(self):
        """Titles that merely contain 'tech'/'data' must not be treated as IT roles."""
        self.assertFalse(is_valid_job("Ejendomsservicetekniker elev søges til AARHUS TECH", "8000", "AARHUS TECH", "Aarhus"))
        self.assertFalse(is_valid_job("Automatikteknikerlærling", "8000", "Novo", "Aarhus"))
        self.assertFalse(is_valid_job("Elektrikerlærling", "8000", "Novo", "Aarhus"))
        # Generic datatekniker-family term must still pass
        self.assertTrue(is_valid_job("Datafaglig elev", "8000", "Firma", "Aarhus"))
        # The generic word "udvikling" (career/business development) must NOT make
        # a non-IT apprenticeship pass — it previously caused false positives
        self.assertFalse(is_valid_job("Kontorelev i HK – mening, udvikling og stærke karrieremuligheder", "8220", "HK", "Brabrand"))
        # But an actual developer-apprentice compound must still pass
        self.assertTrue(is_valid_job("Udviklerelev", "8000", "Firma", "Aarhus"))

    def test_job_priority_ranking(self):
        """Programming ranks highest, then security, then infrastructure, then generic IT."""
        self.assertEqual(job_priority("Datatekniker med speciale i programmering"), 3)
        self.assertEqual(job_priority("Softwareudvikler elev"), 3)
        self.assertEqual(job_priority("Programmørelev"), 3)
        self.assertEqual(job_priority("Datatekniker med speciale i cybersikkerhed"), 2)
        self.assertEqual(job_priority("IT-sikkerheds elev"), 2)
        self.assertEqual(job_priority("Datatekniker med speciale i infrastruktur"), 1)
        self.assertEqual(job_priority("IT-drift elev"), 1)
        self.assertEqual(job_priority("Datatekniker elev"), 1)
        self.assertEqual(job_priority("IT-elev"), 0)
        self.assertEqual(job_priority("Butikselev"), 0)

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
