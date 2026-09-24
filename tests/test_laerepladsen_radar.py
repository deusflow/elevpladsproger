import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import laerepladsen_radar


class TestLaerepladsenRadar(unittest.TestCase):
    def test_detect_new_accreditation(self):
        """Newly accredited companies with Datatekniker approvals must trigger a new_accreditation alert."""
        accredited_places = [{
            "name": "New Tech ApS",
            "cvr": "12345678",
            "postal_code": "8000",
            "city": "Aarhus",
            "has_active_opslag": False,
            "approvals": [{
                "id": "app-1",
                "specialty": "Datatekniker med speciale i programmering",
                "active_students": 0,
                "approved_date": "2026-09-01",
                "next_expiry": None
            }]
        }]

        empty_registry = {}
        alerts, updated_registry = laerepladsen_radar.detect_radar_alerts(accredited_places, empty_registry)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "new_accreditation")
        self.assertEqual(alerts[0]["name"], "New Tech ApS")
        self.assertIn("12345678_app-1", updated_registry)

    def test_detect_contract_expiring_soon(self):
        """Apprentice contracts expiring within 15-150 days should trigger contract_expiring alert."""
        exp_date = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
        accredited_places = [{
            "name": "Existing Tech A/S",
            "cvr": "87654321",
            "postal_code": "8260",
            "city": "Aarhus",
            "has_active_opslag": False,
            "approvals": [{
                "id": "app-2",
                "specialty": "Datatekniker med speciale i programmering",
                "active_students": 1,
                "approved_date": "2021-01-01",
                "next_expiry": exp_date
            }]
        }]

        # Company was seen 60 days ago (past the 45-day cooldown)
        old_seen = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        existing_registry = {
            "87654321_app-2": {
                "name": "Existing Tech A/S",
                "last_seen_at": old_seen,
                "last_alerted_at": old_seen,
                "active_students": 1,
                "next_expiry": exp_date
            }
        }

        alerts, updated = laerepladsen_radar.detect_radar_alerts(accredited_places, existing_registry)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], "contract_expiring")
        self.assertIn("kontrakt udløber om", alerts[0]["tip"])
        self.assertIn(exp_date, alerts[0]["tip"])

    def test_cooldown_prevents_duplicate_radar_spam(self):
        """If an alert was sent recently (< 45 days), it should NOT be resent on subsequent runs."""
        exp_date = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
        accredited_places = [{
            "name": "Existing Tech A/S",
            "cvr": "87654321",
            "postal_code": "8260",
            "city": "Aarhus",
            "has_active_opslag": False,
            "approvals": [{
                "id": "app-2",
                "specialty": "Datatekniker med speciale i programmering",
                "active_students": 1,
                "approved_date": "2021-01-01",
                "next_expiry": exp_date
            }]
        }]

        # Alerted 5 days ago (within cooldown)
        recent_seen = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        existing_registry = {
            "87654321_app-2": {
                "name": "Existing Tech A/S",
                "last_seen_at": recent_seen,
                "last_alerted_at": recent_seen,
                "active_students": 1,
                "next_expiry": exp_date
            }
        }

        alerts, updated = laerepladsen_radar.detect_radar_alerts(accredited_places, existing_registry)
        self.assertEqual(len(alerts), 0)

    def test_format_radar_telegram_message(self):
        """Telegram message formatting should include HTML tags, CVR links, and actionable tips."""
        alert = {
            "type": "new_accreditation",
            "name": "Acme Software",
            "cvr": "99887766",
            "postal_code": "8800",
            "city": "Viborg",
            "specialty": "Datatekniker med speciale i programmering",
            "active_students": 0,
            "next_expiry": None,
            "tip": "Test recommendation"
        }
        msg = laerepladsen_radar.format_radar_telegram_message(alert)
        self.assertIn("Acme Software", msg)
        self.assertIn("8800 Viborg", msg)
        self.assertIn("https://datacvr.virk.dk/enhed/virksomhed/99887766", msg)
        self.assertIn("Test recommendation", msg)

    @patch("laerepladsen_radar.httpx.AsyncClient")
    def test_fetch_laerepladsen_all_mocked(self, mock_client_cls):
        """Verify fetch_laerepladsen_all parses active opslag and filters accredited places."""
        import asyncio
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "antalSider": 1,
            "laeresteder": [{
                "navn": "Mercantec Viborg Partner",
                "cvr": "11223344",
                "postnummer": "8800",
                "kommune": "Viborg",
                "region": "Region Midtjylland",
                "antalAnsatte": "100",
                "opslag": [{
                    "id": "op-999",
                    "titel": "Datateknikerelev i Viborg",
                    "kontaktPerson": "Peter Jensen",
                    "kontaktTelefon": "12345678",
                    "kontaktEmail": "pj@example.com",
                    "ansoegningsfrist": "2026-10-15"
                }],
                "godkendelser": [{
                    "id": "g-1",
                    "speciale": {"navn": "Datatekniker med speciale i programmering"},
                    "antalEleverIgang": 1,
                    "godkendtDato": "2020-01-01",
                    "naesteUdloeb": "2027-01-01",
                    "aktiv": True
                }]
            }]
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        jobs, accredited = asyncio.run(laerepladsen_radar.fetch_laerepladsen_all(max_concurrency=2))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Datateknikerelev i Viborg")
        self.assertEqual(jobs[0]["contact_person"], "Peter Jensen")
        self.assertEqual(jobs[0]["contact_phone"], "12345678")
        self.assertEqual(jobs[0]["contact_email"], "pj@example.com")
        self.assertEqual(jobs[0]["deadline"], "2026-10-15")

        self.assertEqual(len(accredited), 1)
        self.assertEqual(accredited[0]["name"], "Mercantec Viborg Partner")


if __name__ == "__main__":
    unittest.main()
