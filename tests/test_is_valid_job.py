import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scrapers import is_valid_job


class TestIsValidJobLegacy(unittest.TestCase):
    def test_geo_filter_bypass(self):
        self.assertTrue(is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=True))

    def test_geo_filter_standard(self):
        self.assertFalse(is_valid_job("IT-Elev", "", "Vestas", "", bypass_geo=False))

    def test_support_exclusion(self):
        self.assertFalse(is_valid_job("IT-supporter elev", "8000", "Company", ""))
        self.assertFalse(is_valid_job("Helpdesk supporter", "8000", "Company", ""))

    def test_programming_datatekniker(self):
        self.assertTrue(is_valid_job("Datatekniker elev", "8000", "Company", ""))
        self.assertTrue(is_valid_job("Datatekniker med speciale i programmering", "8000", "Company", ""))


if __name__ == "__main__":
    unittest.main()
