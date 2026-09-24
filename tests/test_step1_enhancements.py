import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from scrapers import is_valid_job
from utils import are_jobs_duplicate, normalize_company_name, extract_title_tokens, normalize_job_url


class TestStep1LinguisticsAndDeduplication(unittest.TestCase):
    def test_job_queries_focused(self):
        """JOB_QUERIES should contain targeted apprenticeship queries and exclude broad senior developer terms."""
        self.assertIn("datatekniker", config.JOB_QUERIES)
        self.assertIn("datateknikerelev", config.JOB_QUERIES)
        self.assertIn("it-elev", config.JOB_QUERIES)
        self.assertIn("software apprentice", config.JOB_QUERIES)
        # Verify broad senior terms that wasted scraper pages are removed
        self.assertNotIn("softwareudvikler", config.JOB_QUERIES)
        self.assertNotIn("programmering", config.JOB_QUERIES)

    def test_hybrid_supporter_datatekniker_allowed(self):
        """Dual-role and hybrid apprenticeships mentioning both supporter and datatekniker/programming must NOT be rejected."""
        self.assertTrue(is_valid_job("IT-supporter / Datatekniker elev", "8000", "Midt IT", "Aarhus"))
        self.assertTrue(is_valid_job("Elev til IT-support og softwareudvikling", "8000", "Midt IT", "Aarhus"))
        self.assertTrue(is_valid_job("IT-elev (Drift og Programmering)", "8000", "Midt IT", "Aarhus"))

    def test_pure_supporter_rejected(self):
        """Pure IT support and helpdesk without datatekniker or programming should still be rejected."""
        self.assertFalse(is_valid_job("IT-supporter elev", "8000", "Midt IT", "Aarhus"))
        self.assertFalse(is_valid_job("Helpdesk supporter trainee", "8000", "Midt IT", "Aarhus"))
        self.assertFalse(is_valid_job("Servicedesk elev", "8000", "Midt IT", "Aarhus"))

    def test_english_apprentice_support(self):
        """English apprenticeship titles from international firms must pass validation."""
        self.assertTrue(is_valid_job("Software Developer Apprentice", "7190", "LEGO Group", "Billund"))
        self.assertTrue(is_valid_job("IT Apprentice", "8850", "Grundfos", "Bjerringbro"))
        self.assertTrue(is_valid_job("Cybersecurity Apprentice", "8000", "International Tech", "Aarhus"))

    def test_geo_fallback_on_city_in_title_or_company(self):
        """If postal_code is empty, city mentioned in company or title should allow Midtjylland jobs."""
        # Aarhus Kommune without postal code
        self.assertTrue(is_valid_job("Datateknikerelev", "", "Aarhus Kommune", ""))
        # Title mentions Viborg with empty postal
        self.assertTrue(is_valid_job("Datatekniker elev i Viborg", "", "Midt IT", ""))
        # Non-target region in title must be rejected
        self.assertFalse(is_valid_job("Datatekniker elev i København", "", "Tech A/S", ""))

    def test_normalize_company_name(self):
        """Legal entity suffixes and punctuation should be cleaned."""
        self.assertEqual(normalize_company_name("Systematic A/S"), "systematic")
        self.assertEqual(normalize_company_name("Systematic ApS"), "systematic")
        self.assertEqual(normalize_company_name("LEGO Group"), "lego")
        self.assertEqual(normalize_company_name("Aarhus Kommune"), "aarhus")

    def test_extract_title_tokens(self):
        """Compound apprentice words in Danish should be expanded."""
        tokens = extract_title_tokens("Datateknikerelev med speciale i programmering")
        self.assertIn("datatekniker", tokens)
        self.assertIn("elev", tokens)
        self.assertIn("programmering", tokens)
        self.assertNotIn("med", tokens)
        self.assertNotIn("i", tokens)

    def test_are_jobs_duplicate_cross_portal(self):
        """Identical postings across different portals with naming variations must be detected as duplicates."""
        job1 = {
            "company": "Systematic A/S",
            "title": "Datateknikerelev med speciale i programmering",
            "url": "https://www.jobindex.dk/job/12345?utm_source=feed"
        }
        job2 = {
            "company": "Systematic",
            "title": "Datatekniker elev - programmering",
            "url": "https://jobnet.dk/find-job/details/998877"
        }
        self.assertTrue(are_jobs_duplicate(job1, job2))

    def test_are_jobs_duplicate_url_normalization(self):
        """Exact same job URL with differing tracking params must match."""
        job1 = {"company": "Tech Corp", "title": "IT-Elev", "url": "https://example.com/job/1?utm_medium=cpc"}
        job2 = {"company": "Other Name", "title": "Other Title", "url": "https://example.com/job/1?utm_source=twitter"}
        self.assertTrue(are_jobs_duplicate(job1, job2))

    def test_distinct_specializations_not_duplicate(self):
        """Programming vs Infrastructure at the same company must NOT be treated as duplicates."""
        job_prog = {
            "company": "LEGO Group",
            "title": "Datateknikerelev (Programmering)",
            "url": "https://lego.com/jobs/101"
        }
        job_infra = {
            "company": "LEGO Group",
            "title": "Datateknikerelev (Infrastruktur)",
            "url": "https://lego.com/jobs/102"
        }
        self.assertFalse(are_jobs_duplicate(job_prog, job_infra))


if __name__ == "__main__":
    unittest.main()
