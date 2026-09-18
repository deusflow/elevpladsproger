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
        company_validator.set_validation_cache({"cached_test_co": True, "cached_fake_co": False})
        cache = company_validator.get_validation_cache()
        self.assertTrue(cache.get("cached_test_co"))
        self.assertFalse(cache.get("cached_fake_co"))

    def test_cvr_accreditation_mocked(self):
        """Verify check_accreditation properly recognizes DB07 IT codes and handles None safely."""
        import asyncio
        from unittest.mock import patch

        class MockResponse:
            def __init__(self, status_code, json_data):
                self.status_code = status_code
                self._json = json_data

            def json(self):
                return self._json

        async def run_checks():
            # 1. DB07 code 62 (Computer programming) with 2 employees -> True
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"industrycode": 620100, "employees": 2})):
                self.assertTrue(await company_validator.check_accreditation("Test Prog ApS"))

            # 2. DB07 code 58 (Software publishing) -> True
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"industrycode": "582900", "employees": 1})):
                self.assertTrue(await company_validator.check_accreditation("Test Game Studio"))

            # 3. Non-IT with >10 employees -> True
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"industrycode": "105100", "employees": 25})):
                self.assertTrue(await company_validator.check_accreditation("Large Dairy Co"))

            # 4. Non-IT with <=10 employees -> False
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"industrycode": "471100", "employees": 3})):
                self.assertFalse(await company_validator.check_accreditation("Small Bakery"))

            # 5. Null/missing fields -> False safely without NameError or TypeError
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"industrycode": None, "employees": None})):
                self.assertFalse(await company_validator.check_accreditation("Corrupted Record ApS"))

            # 6. CVR Error response -> False
            with patch("httpx.AsyncClient.get", return_value=MockResponse(200, {"error": "NOT_FOUND"})):
                self.assertFalse(await company_validator.check_accreditation("Ghost Corp"))

        asyncio.run(run_checks())


if __name__ == "__main__":
    unittest.main()
