"""Regression tests for the geographic scope expansion:

- Target regions extended from Midtjylland-only to Jutland + Funen
  (Region Midtjylland, Nordjylland, Syddanmark).
- Jobnet BFF receives repeated `regions` params for every target region.
- Jobindex / IT-Jobbank iterate the shared TARGET_REGION_SLUGS list.
- Lærepladsen radar uses 5 geo centers with per-center radius.
- is_valid_job accepts an extra_text (ad body) used ONLY as a positive
  elev/datatekniker signal.
"""
import unittest
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scrapers import is_valid_job, NON_TARGET_REGION_PATTERN
import laerepladsen_radar


class TestExtraTextElevSignal(unittest.TestCase):
    def test_body_elev_fallback(self):
        """A non-elev title is accepted when the ad body explicitly says elev/datatekniker."""
        self.assertTrue(is_valid_job(
            "Netværkstekniker", "8000", "Firma", "Aarhus",
            extra_text="Vi søger en datateknikerelev til vores it-afdeling i Aarhus."
        ))
        # Title "Datatekniker" + body also carrying an elevplads signal passes
        self.assertTrue(is_valid_job(
            "Datatekniker", "9000", "Nord IT", "Aalborg",
            extra_text="Dette er en elevplads med læreansættelse."
        ))

    def test_body_fallback_not_used_for_skill_bypass(self):
        """An apprenticeship offer in the body must NOT open the IT gate for
        trades with no technical specialisation words in the title."""
        self.assertFalse(is_valid_job(
            "Butiksassistent", "8000", "Firma", "Aarhus",
            extra_text="Vi søger en elevpladskandidat til vores butik."
        ))
        # Technical titles (drift/netværk/programm...) DO open the gate:
        self.assertTrue(is_valid_job(
            "Driftstekniker", "8000", "Firma", "Aarhus",
            extra_text="Vi søger en elevpladskandidat til vedligeholdelse."
        ))

    def test_extra_text_strips_html(self):
        """HTML markup in the Jobnet description must not hide the signals."""
        self.assertTrue(is_valid_job(
            "Netværkstekniker", "8000", "Firma", "Aarhus",
            extra_text="<p>Vi søger en datatekniker-elev</p><p>Vi tilbyder lærlingekontrakt</p>"
        ))

    def test_extra_text_never_used_for_exclusions(self):
        """Bodies often mention 'support'; that must NOT disqualify the job."""
        self.assertTrue(is_valid_job(
            "Datateknikerelev til programmering", "8000", "Firma", "Aarhus",
            extra_text="Supportkontoret er placeret i samme bygning."
        ))

    def test_no_extra_text_unchanged(self):
        """Without extra_text the elev requirement stays title-only."""
        self.assertFalse(is_valid_job("Netværkstekniker", "8000", "Firma", "Aarhus"))

    def test_body_scan_never_matches_english_embedded_elev(self):
        """English words like 'relevant' embed 'elev' — they must never satisfy
        the apprenticeship signal (live-found regression: Jobnet senior
        developer ads passed because of the word 'relevant')."""
        senior_body = (
            "<p>You have several years of relevant software development "
            "experience and strong skills in C# and Angular.</p>"
        )
        self.assertFalse(is_valid_job(
            "Senior Software Developer", "8000", "Firma", "Aarhus",
            extra_text=senior_body
        ))
        # A Danish body mentioning the word 'elevator' must also not trigger
        self.assertFalse(is_valid_job(
            "Software Engineer", "8000", "Firma", "Aarhus",
            extra_text="Dette kontorhus nyder godt af nyliftede ... cooler" 
        ))
        self.assertFalse(is_valid_job(
            "Software Engineer", "8000", "Firma", "Aarhus",
            extra_text="Der er elevator i bygningen og fint kantineudbuder."
        ))

    def test_body_scan_matches_danish_inflections(self):
        """Real Danish apprenticeship wording in the body must create eligibility."""
        for body in (
            "Vi tilbyder en elevplads med læreansættelse fra 1. januar.",
            "Som datateknikerelev bliver du oplært af vores rutinerede udviklere.",
            "Kontrakten er en lærlingeplads i vores IT-afdeling.",
            "Vi har elevpladser i vores IT-afdeling igen.",
            "This is a software apprenticeship program.",
        ):
            self.assertTrue(
                is_valid_job("Netværkstekniker", "8000", "Firma", "Aarhus", extra_text=body),
                msg=body,
            )

    def test_body_scan_never_treats_pupils_as_offer(self):
        """Bodies that merely mention 'elever'/'eleverne' (school pupils) or a
        required 'datatekniker' education must NOT signal an apprenticeship."""
        for body in (
            "Elever og eleverne får en fast mentor i afdelingen.",
            "Vi daglige rammer for ca. 650 elever og 120 engagerede medarbejdere.",
            "Det kræver en datatekniker-uddannelse og flere års erfaring.",
        ):
            self.assertFalse(
                is_valid_job("Teamleder", "8000", "Firma", "Aarhus", extra_text=body),
                msg=body,
            )

    def test_non_target_region_pattern(self):
        """Zealand/Copenhagen/Bornholm excluded; Funen words are not in the pattern."""
        for word in ("København", "Roskilde", "Bornholm", "Nordsjælland", "Lyngby"):
            self.assertIsNotNone(NON_TARGET_REGION_PATTERN.search(word.lower()), msg=word)
        for word in ("fyn", "odense", "svendborg", "middelfart", "nyborg", "aalborg"):
            self.assertIsNone(NON_TARGET_REGION_PATTERN.search(word), msg=word)


class TestRadarRegionExpansion(unittest.TestCase):
    def test_geo_centers_under_api_cap(self):
        """All (lat, lng, radius) centers must cover the three target regions."""
        centers = laerepladsen_radar.REGION_SEARCH_CENTERS
        self.assertTrue(2 <= len(centers) <= 5)
        for lat, lng, radius in centers:
            self.assertTrue(50.0 < float(lat) < 60.0, msg=lat)
            self.assertTrue(8.0 < float(lng) < 12.0, msg=lng)
            self.assertTrue(50 <= int(radius) <= 130, msg=radius)
        self.assertEqual(centers[0][0], laerepladsen_radar.MIDTJYLLAND_SEARCH_CENTERS[0][0])

    def test_place_in_target_region(self):
        """Region labels of all three target regions (plus in-range postals) are accepted."""
        for region in ("Region Midtjylland", "Region Nordjylland", "Region Syddanmark"):
            place = {"region": region, "postnummer": ""}
            self.assertTrue(laerepladsen_radar._place_in_target_region(place), msg=region)
        out_of_scope = [
            {"region": "Region Hovedstaden", "postnummer": ""},
            {"region": "Region Sjælland", "postnummer": ""},
            {"region": "", "postnummer": 1050},
            {"region": "", "postnummer": 4000},
        ]
        for place in out_of_scope:
            self.assertFalse(laerepladsen_radar._place_in_target_region(place), msg=str(place))

    def test_postal_beats_region_name(self):
        """A target-range postal passes even when the API region label is odd."""
        place = {"region": "Ukendt", "postnummer": 9000}
        self.assertTrue(laerepladsen_radar._place_in_target_region(place))


class TestTargetCompaniesExpansion(unittest.TestCase):
    def test_json_valid_and_new_municipalities_present(self):
        """target_companies.json must stay valid and include the newly added scope."""
        with open(config.TARGET_COMPANIES_PATH) as f:
            companies = json.load(f)
        self.assertGreater(len(companies), 60)
        names = {c["name"].lower() for c in companies}
        for municipality in ("vejle kommune", "kolding kommune", "haderslev kommune",
                             "middelfart kommune", "esbjerg kommune"):
            self.assertIn(municipality, names, msg=municipality)
        for company in companies:
            self.assertIn("url", company)
            self.assertTrue(company["url"].startswith("https://"), msg=company["name"])


if __name__ == "__main__":
    unittest.main()
