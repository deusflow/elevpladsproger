import unittest
import asyncio
from unittest.mock import patch, MagicMock
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import company_scrapers


class TestStep3ATSIntegrations(unittest.TestCase):
    def test_try_emply_api_with_section_id(self):
        """Emply career portal with sectionId should query get-page and parse IT elev vacancies."""
        html_content = """
        <html>
        <script>
        var config = {
            count: 6,
            sectionId: '26bc2ca9-80c9-403f-bccf-c0430348ad0c',
            langCode: 'da-DK'
        };
        </script>
        </html>
        """
        api_response = {
            "vacancies": [
                {
                    "id": "v-1",
                    "shortId": "abc123",
                    "title": "Datatekniker elev til IT-infrastruktur og drift",
                    "titleAsUrl": "datatekniker-elev-til-it-infrastruktur-og-drift"
                },
                {
                    "id": "v-2",
                    "shortId": "xyz789",
                    "title": "Kokkemedhjælper til kantinen",
                    "titleAsUrl": "kokkemedhjaelper"
                }
            ]
        }

        class MockRespGet:
            status_code = 200
            text = html_content
            headers = {"content-type": "text/html"}

        class MockRespPost:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self):
                return api_response

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockRespGet()), \
                 patch("httpx.AsyncClient.post", return_value=MockRespPost()):
                items = await company_scrapers.try_emply_api("Silkeborg Kommune", "https://silkeborg.career.emply.com/ledige-stillinger")
                self.assertIsNotNone(items)
                jobs = [i for i in items if i.get("type") != "hash"]
                hashes = [i for i in items if i.get("type") == "hash"]

                self.assertEqual(len(jobs), 1)
                self.assertIn("Datatekniker elev", jobs[0]["title"])
                self.assertEqual(jobs[0]["source"], "EmplyAPI")
                self.assertEqual(len(hashes), 1)
                self.assertEqual(hashes[0]["company"], "Silkeborg Kommune")

        asyncio.run(run_test())

    def test_try_emply_api_embedded_dycon(self):
        """Aarhus University style embedded DYCON.EmplyData JSON should be parsed directly."""
        html_content = """
        <html>
        <script>
        DYCON.EmplyData.c2502676.vacancies = [
            {
                "id": 101,
                "title": "Datateknikerelev med speciale i programmering",
                "link": "/om/stillinger/job/datateknikerelev-101",
                "location": {"name": "Aarhus C", "zip": 8000}
            },
            {
                "id": 102,
                "title": "Ph.d.-stipendiat i Molekylærbiologi",
                "link": "/om/stillinger/job/phd-102",
                "location": {"name": "Aarhus C", "zip": 8000}
            }
        ];
        </script>
        </html>
        """
        class MockRespGet:
            status_code = 200
            text = html_content
            headers = {"content-type": "text/html"}

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockRespGet()):
                items = await company_scrapers.try_emply_api("Aarhus Universitet", "https://au.dk/om/stillinger/teknisk-administrative-stillinger/")
                self.assertIsNotNone(items)
                jobs = [i for i in items if i.get("type") != "hash"]
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["company"], "Aarhus Universitet")
                self.assertIn("programmering", jobs[0]["title"])

        asyncio.run(run_test())

    def test_try_teamtailor_api_extraction(self):
        """Teamtailor API should parse items, extract valid apprenticeships, and return structural hash."""
        api_response = {
            "items": [
                {
                    "id": 501,
                    "title": "Software Developer Apprentice (Datatekniker)",
                    "url": "https://bankdata.teamtailor.com/jobs/501"
                },
                {
                    "id": 502,
                    "title": "Senior Cloud Architect",
                    "url": "https://bankdata.teamtailor.com/jobs/502"
                }
            ]
        }
        class MockResp:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self):
                return api_response

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockResp()):
                items = await company_scrapers.try_teamtailor_api("Bankdata", "https://bankdata.teamtailor.com")
                self.assertIsNotNone(items)
                jobs = [i for i in items if i.get("type") != "hash"]
                hashes = [i for i in items if i.get("type") == "hash"]

                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["source"], "TeamtailorAPI")
                self.assertEqual(len(hashes), 1)

        asyncio.run(run_test())

    def test_try_workday_api_extraction(self):
        """Workday JSON CXS API should parse postings for LEGO Group without Playwright."""
        api_response = {
            "total": 2,
            "jobPostings": [
                {
                    "title": "IT Software Apprentice - Digital Technology",
                    "externalPath": "/job/Billund/IT-Apprentice_001",
                    "bulletFields": ["Apprentice", "Billund"]
                },
                {
                    "title": "Packaging Machine Operator",
                    "externalPath": "/job/Billund/Operator_002",
                    "bulletFields": ["Production"]
                }
            ]
        }
        class MockRespPost:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self):
                return api_response

        async def run_test():
            with patch("httpx.AsyncClient.post", return_value=MockRespPost()):
                items = await company_scrapers.try_workday_api("LEGO Group", "https://lego.wd103.myworkdayjobs.com/LEGO_External")
                self.assertIsNotNone(items)
                jobs = [i for i in items if i.get("type") != "hash"]
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["source"], "WorkdayAPI")
                self.assertIn("Billund", jobs[0]["url"])

        asyncio.run(run_test())

    def test_try_signatur_api_extraction(self):
        """Signatur.dk HTML parser should extract jobs from municipal portals."""
        html_content = """
        <html>
        <body>
            <a href="/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=2289&WebAdId=101">
                Kategori: IT og Digitalisering. Stilling: Datatekniker elev til IT-afdelingen. Ansøgningsfrist: 1. oktober 2026
            </a>
            <a href="/ExtJobs/DefaultHosting/JobDetails.aspx?ClientId=2289&WebAdId=102">
                Kategori: Sundhed. Stilling: Social- og sundhedsassistent. Ansøgningsfrist: 2. oktober 2026
            </a>
        </body>
        </html>
        """
        class MockRespGet:
            status_code = 200
            text = html_content
            headers = {"content-type": "text/html"}

        async def run_test():
            with patch("httpx.AsyncClient.get", return_value=MockRespGet()):
                items = await company_scrapers.try_signatur_api("Horsens Kommune", "https://portal.signatur.dk/ExtJobs/DefaultHosting/JobList.aspx?clientid=2289")
                self.assertIsNotNone(items)
                jobs = [i for i in items if i.get("type") != "hash"]
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["source"], "Signatur")
                self.assertIn("Datatekniker elev", jobs[0]["title"])

        asyncio.run(run_test())

    def test_scrape_company_bypasses_browser_when_ats_matches(self):
        """When an ATS API matches, scrape_company must immediately return without invoking page.goto."""
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.new_page = MagicMock(return_value=mock_page)

        async def run_test():
            mock_items = [
                {"job_id": "test_id", "title": "IT-elev", "company": "Test Co", "url": "https://example.com/job", "source": "TeamtailorAPI"},
                {"type": "hash", "company": "Test Co", "url": "https://example.com/jobs", "hash": "abc"}
            ]
            with patch("company_scrapers.try_teamtailor_api", return_value=mock_items):
                sem = asyncio.Semaphore(1)
                company = {"name": "Test Co", "url": "https://example.com/jobs"}
                res = await company_scrapers.scrape_company(mock_context, company, sem)

                self.assertEqual(res, mock_items)
                # Verify browser page was NOT opened
                mock_context.new_page.assert_not_called()
                self.assertEqual(company.get("fail_count"), 0)

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
