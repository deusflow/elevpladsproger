import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import company_validator


class TestCompanyValidator(unittest.TestCase):
    def test_whitelist_public_sector(self):
        """Municipalities, regions, universities, and schools should be approved without network."""
        self.assertTrue(company_validator.is_known_approved_company("Aarhus Kommune"))
        self.assertTrue(company_validator.is_known_approved_company("Region Midtjylland"))
        self.assertTrue(company_validator.is_known_approved_company("Aarhus Universitet"))
        self.assertTrue(company_validator.is_known_approved_company("Mercantec"))
        self.assertTrue(company_validator.is_known_approved_company("Skoleoplæringscenter"))

    def test_whitelist_target_enterprises(self):
        """Companies from target_companies.json and config.TARGET_ENTERPRISES should be recognized."""
        self.assertTrue(company_validator.is_known_approved_company("Arla"))
        self.assertTrue(company_validator.is_known_approved_company("Lego System A/S"))
        self.assertTrue(company_validator.is_known_approved_company("Vestas Wind Systems"))

    def test_unknown_company_not_whitelisted(self):
        """Random unverified company name should not pass the instant whitelist."""
        self.assertFalse(company_validator.is_known_approved_company("NonExistentXYZ12345Corp"))

    def test_cache_management(self):
        """Validation cache should correctly store, retrieve, and update entries."""
        initial = company_validator.get_validation_cache()
        company_validator.set_validation_cache({"cached_test_co": True, "cached_fake_co": False})
        cache = company_validator.get_validation_cache()
        self.assertTrue(cache.get("cached_test_co"))
        self.assertFalse(cache.get("cached_fake_co"))


if __name__ == "__main__":
    unittest.main()
