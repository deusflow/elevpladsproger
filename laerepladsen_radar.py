import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import httpx
import config
from scrapers import format_job, is_valid_job, job_priority

logger = logging.getLogger("elevplads_scraper")

LAEREPLADSEN_BASE_API = "https://sr.laerepladsen.dk/api/soeg-opslag"
UDDANNELSE_NAME = "Data- og kommunikationsuddannelsen"

# Datatekniker specialisations we track. "It-supporter" is deliberately excluded
# per the project requirement (Datatekniker except IT-support).
# Order matters: programming is the main focus and is queried/first-collected.
TARGET_SPECIALTIES = [
    "Datatekniker med speciale i programmering",
    "Datatekniker med speciale i cybersikkerhed",
    "Datatekniker med speciale i infrastruktur",
]

# The Lærepladsen API hard-caps every query at 500 companies ("Vi viser kun de
# første 500"). The old code fetched the first 500 companies NATIONALLY and then
# kept only Midtjylland rows, silently dropping many regional employers.
#
# Instead we anchor the search on regional coordinates covering Jutland + Funen
# (the three target regions) and query ONE SPECIALISATION AT A TIME. All
# Optimized regional search centers covering Jutland + Funen (Midtjylland, Nordjylland, Syddanmark).
# Sized to stay safely under Lærepladsen's 50-page (500 company) pagination cap while
# minimizing overlapping duplicate API roundtrips.
REGION_SEARCH_CENTERS: list[tuple[str, str, str]] = [
    ("56.8", "9.8", "120"),    # Midtjylland & Nordjylland (Aarhus, Aalborg, Viborg, Herning, Randers)
    ("55.4", "9.8", "110"),    # Syddanmark & Fyn (Odense, Vejle, Kolding, Esbjerg, Sønderborg)
]

# Backwards-compatible alias for the Midtjylland-only era (lat, lng tuples).
MIDTJYLLAND_SEARCH_CENTERS = [(lat, lng) for lat, lng, _radius in REGION_SEARCH_CENTERS]
MIDTJYLLAND_RADIUS_KM = "120"


def _place_in_target_region(place: dict) -> bool:
    """Region/postal check for a Lærepladsen learning place against the target regions."""
    region = (place.get("region", "") or "").lower()
    postal = str(place.get("postnummer", ""))
    if postal in config.TARGET_POSTAL_CODES:
        return True
    return (
        "midtjylland" in region
        or "nordjylland" in region
        or "syddanmark" in region
    )


def _merge_place(existing: dict, incoming: dict) -> None:
    """Merge opslag/godkendelser from a duplicate place into the kept record."""
    seen_g = {g.get("id") for g in existing.get("godkendelser", [])}
    for g in incoming.get("godkendelser", []):
        if g.get("id") not in seen_g:
            existing.setdefault("godkendelser", []).append(g)
            seen_g.add(g.get("id"))

    seen_op = {o.get("id") for o in existing.get("opslag", [])}
    for o in incoming.get("opslag", []):
        if o.get("id") not in seen_op:
            existing.setdefault("opslag", []).append(o)
            seen_op.add(o.get("id"))


async def fetch_laerepladsen_all(max_concurrency: int = 8) -> tuple[list[dict], list[dict]]:
    """Fetch all Datatekniker learning places and active postings in the target regions (Jutland + Funen).

    Returns:
        (active_jobs, accredited_places_in_target_regions)
    """
    udd_encoded = urllib.parse.quote(UDDANNELSE_NAME)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    client_kwargs: dict[str, Any] = {"timeout": 12.0, "follow_redirects": True, "headers": headers}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    all_places: list[dict] = []
    active_jobs: list[dict] = []
    pages_fetched = 0

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            sem = asyncio.Semaphore(max_concurrency)

            async def fetch_json(spec_encoded: str, page_num: int, params: Optional[dict]) -> Optional[dict]:
                async with sem:
                    url = f"{LAEREPLADSEN_BASE_API}/{page_num}/{udd_encoded}/{spec_encoded}"
                    try:
                        r = await client.get(url, params=params)
                        if r.status_code == 200:
                            return r.json()
                        logger.warning(f"Lærepladsen HTTP {r.status_code} for page {page_num} ({spec_encoded})")
                    except Exception as e:
                        logger.warning(f"Error fetching Lærepladsen page {page_num}: {e}")
                    return None

            for spec in TARGET_SPECIALTIES:
                spec_encoded = urllib.parse.quote(spec)
                for center_lat, center_lng, radius_km in REGION_SEARCH_CENTERS:
                    params = {
                        "latitude": center_lat,
                        "longitude": center_lng,
                        "afstand": radius_km,
                    }
                    first = await fetch_json(spec_encoded, 0, params)
                    if not first:
                        # Fallback: retry without the geo restriction so a transient
                        # geo failure does not blind the whole radar.
                        first = await fetch_json(spec_encoded, 0, None)
                    if not first:
                        logger.warning(f"Lærepladsen: no data for speciale '{spec}' @ {center_lat},{center_lng}")
                        continue

                    all_places.extend(first.get("laeresteder", []))
                    total_pages = min(int(first.get("antalSider", 1) or 1), 50)
                    pages_fetched += 1

                    if total_pages > 1:
                        tasks = [fetch_json(spec_encoded, p, params) for p in range(1, total_pages)]
                        for data in await asyncio.gather(*tasks):
                            if data:
                                all_places.extend(data.get("laeresteder", []))
                                pages_fetched += 1

    except Exception as e:
        logger.error(f"Failed to communicate with Lærepladsen API: {e}")
        return [], []

    # De-duplicate places (the same company can appear under multiple specialer).
    unique_places: dict[str, dict] = {}
    for place in all_places:
        key = str(place.get("pnr") or place.get("cvr") or place.get("navn") or "")
        if key in unique_places:
            _merge_place(unique_places[key], place)
        else:
            unique_places[key] = place
    all_places = list(unique_places.values())

    logger.info(
        f"Lærepladsen API returned {len(all_places)} unique learning places "
        f"across {pages_fetched} pages / {len(TARGET_SPECIALTIES)} specialer"
    )

    # Filter for target-region employers & extract active postings
    accredited_places = []
    seen_opslag_ids = set()

    for place in all_places:
        region = place.get("region", "")
        postal = str(place.get("postnummer", ""))
        if not _place_in_target_region(place):
            continue

        company_name = place.get("navn", "Ukendt")
        cvr = str(place.get("cvr", ""))
        city = place.get("kommune", "")

        # 1. Collect relevant Datatekniker accreditations (It-supporter excluded)
        relevant_approvals = []
        for g in place.get("godkendelser", []):
            spec_name = g.get("speciale", {}).get("navn", "")
            spec_lower = spec_name.lower()
            if "supporter" in spec_lower:
                continue
            if "datatekniker" in spec_lower or "programmering" in spec_lower or "cybersikkerhed" in spec_lower:
                relevant_approvals.append({
                    "id": g.get("id"),
                    "specialty": spec_name,
                    "active_students": g.get("antalEleverIgang", 0),
                    "historical_students": g.get("antalEleverHistorisk", 0),
                    "max_places": g.get("antalPladser", 0),
                    "approved_date": g.get("godkendtDato"),
                    "next_expiry": g.get("naesteUdloeb"),
                    "is_active": g.get("aktiv", True)
                })

        default_specialty = relevant_approvals[0]["specialty"] if relevant_approvals else ""

        # 2. Process active postings (opslag)
        postings = place.get("opslag", [])
        for op in postings:
            op_id = str(op.get("id", ""))
            if not op_id or op_id in seen_opslag_ids:
                continue

            op_spec = ""
            spec_field = op.get("speciale")
            if isinstance(spec_field, dict):
                op_spec = spec_field.get("navn", "") or ""

            title = op.get("titel") or op.get("beskrivelse", "")[:60] or "Datateknikerelev"

            # Drop It-supporter postings unless the title clearly signals a
            # programming / software / datatekniker role.
            if "supporter" in op_spec.lower() and job_priority(title) == 0:
                continue

            direct_url = op.get("kontaktHjemmeside")
            job_url = direct_url if (direct_url and direct_url.startswith("http")) else f"https://laerepladsen.dk/elev/opslag/{op_id}"

            if is_valid_job(title, postal, company_name, location=city, bypass_geo=True):
                seen_opslag_ids.add(op_id)
                job_dict = format_job(
                    job_id=f"laerepladsen_{op_id}",
                    title=title,
                    company=company_name,
                    url=job_url,
                    source="Laerepladsen"
                )
                job_dict["specialty"] = op_spec or default_specialty
                job_dict["contact_person"] = op.get("kontaktPerson")
                job_dict["contact_phone"] = op.get("kontaktTelefon")
                job_dict["contact_email"] = op.get("kontaktEmail")
                job_dict["deadline"] = op.get("ansoegningsfrist")
                job_dict["start_date"] = op.get("ansaettelsesdato")
                job_dict["description"] = op.get("beskrivelse")
                active_jobs.append(job_dict)

        if relevant_approvals:
            accredited_places.append({
                "name": company_name,
                "cvr": cvr,
                "pnr": place.get("pnr"),
                "postal_code": postal,
                "city": city,
                "address": place.get("adresse"),
                "employees": place.get("antalAnsatte"),
                "approvals": relevant_approvals,
                "has_active_opslag": len(postings) > 0
            })

    logger.info(f"Lærepladsen Radar identified {len(accredited_places)} Datatekniker accredited employers in the target regions and {len(active_jobs)} active opslag")
    return active_jobs, accredited_places


def detect_radar_alerts(
    accredited_places: list[dict],
    registry_state: dict,
    max_alerts: int = 5,
    silent_baseline: bool = False
) -> tuple[list[dict], dict]:
    """Detect high-value unsolicited application opportunities:
    1. Newly accredited companies (approved within last 60 days)
    2. Zero active students (open capacity)
    3. Current apprentice contract expiring within 15-150 days

    Includes protection against alert storms via silent baseline initialization,
    recency check on accreditation dates, and strict alert capping per run.
    """
    now = datetime.now(timezone.utc)
    updated_registry = registry_state.copy()

    # Silent baseline: populate the registry without triggering historical alert storms
    if silent_baseline:
        for place in accredited_places:
            cvr = place.get("cvr")
            name = place.get("name")
            for app in place.get("approvals", []):
                spec_name = app.get("specialty", "")
                spec_key = f"{cvr}_{app.get('id', spec_name)}"
                updated_registry[spec_key] = {
                    "name": name,
                    "cvr": cvr,
                    "specialty": spec_name,
                    "last_seen_at": now.isoformat(),
                    "last_alerted_at": None,
                    "active_students": app.get("active_students", 0),
                    "next_expiry": app.get("next_expiry"),
                    "alerted_zero_capacity": False,
                }
        logger.info(f"Initialized Lærepladsen registry baseline with {len(updated_registry)} employers silently.")
        return [], updated_registry

    candidate_alerts = []  # tuple: (priority_score, alert_payload, spec_key, active_students, next_expiry)

    for place in accredited_places:
        cvr = place.get("cvr")
        name = place.get("name")
        postal = place.get("postal_code")
        city = place.get("city")

        for app in place.get("approvals", []):
            spec_name = app.get("specialty", "")
            spec_key = f"{cvr}_{app.get('id', spec_name)}"
            existing = registry_state.get(spec_key)

            active_students = app.get("active_students", 0)
            next_expiry = app.get("next_expiry")
            approved_date = app.get("approved_date")

            is_new_company = existing is None
            alert_payload = None
            priority_score = 999.0

            # Check for newly accredited learning places (only if approved in the last 60 days)
            if is_new_company:
                is_recent_approval = False
                if approved_date:
                    try:
                        clean_date = approved_date[:10]
                        app_dt = datetime.strptime(clean_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        diff_days = (now - app_dt).days
                        if 0 <= diff_days <= 60:
                            is_recent_approval = True
                    except Exception:
                        pass

                if is_recent_approval:
                    alert_payload = {
                        "type": "new_accreditation",
                        "name": name,
                        "cvr": cvr,
                        "postal_code": postal,
                        "city": city,
                        "specialty": spec_name,
                        "active_students": active_students,
                        "approved_date": approved_date,
                        "next_expiry": next_expiry,
                        "tip": "Ny-godkendt lærested! Virksomheden har lige fået godkendelse. Send uopfordret ansøgning, før andre opdager dem!"
                    }
                    priority_score = 0.0
            else:
                last_alerted = existing.get("last_alerted_at")
                can_re_alert = True
                if last_alerted:
                    try:
                        last_dt = datetime.fromisoformat(last_alerted)
                        if (now - last_dt) < timedelta(days=45):
                            can_re_alert = False
                    except Exception:
                        can_re_alert = True

                # Check if an apprentice contract is expiring soon (within 15-150 days)
                if can_re_alert and next_expiry:
                    try:
                        clean_exp = next_expiry[:10]
                        exp_dt = datetime.strptime(clean_exp, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        days_until = (exp_dt - now).days
                        if 15 <= days_until <= 150:
                            alert_payload = {
                                "type": "contract_expiring",
                                "name": name,
                                "cvr": cvr,
                                "postal_code": postal,
                                "city": city,
                                "specialty": spec_name,
                                "active_students": active_students,
                                "next_expiry": next_expiry,
                                "days_until": days_until,
                                "tip": f"Nuværende elevs kontrakt udløber om {days_until} dage ({next_expiry})! Perfekt timing til at række ud om næste hold."
                            }
                            # Sooner expiring contracts get higher priority (lower score)
                            priority_score = 1.0 + (days_until / 200.0)
                    except Exception:
                        pass

                # Check for approved programming employers with 0 current students (fresh capacity)
                if not alert_payload and can_re_alert and active_students == 0 and "programmering" in spec_name.lower():
                    if not place.get("has_active_opslag") and not existing.get("alerted_zero_capacity"):
                        alert_payload = {
                            "type": "open_capacity",
                            "name": name,
                            "cvr": cvr,
                            "postal_code": postal,
                            "city": city,
                            "specialty": spec_name,
                            "active_students": 0,
                            "next_expiry": None,
                            "tip": "Virksomheden er godkendt til Datatekniker - Programmering, men har p.t. 0 elever! Stor chance for positiv modtagelse af uopfordret ansøgning."
                        }
                        priority_score = 3.0

            if alert_payload:
                candidate_alerts.append((priority_score, alert_payload, spec_key, name, cvr, spec_name, active_students, next_expiry))
            else:
                updated_registry[spec_key] = {
                    "name": name,
                    "cvr": cvr,
                    "specialty": spec_name,
                    "last_seen_at": now.isoformat(),
                    "last_alerted_at": existing.get("last_alerted_at") if existing else None,
                    "active_students": active_students,
                    "next_expiry": next_expiry,
                    "alerted_zero_capacity": existing.get("alerted_zero_capacity", False) if existing else False
                }

    # Sort candidates by priority score and take up to max_alerts
    candidate_alerts.sort(key=lambda x: x[0])
    selected_alerts_data = candidate_alerts[:max_alerts] if max_alerts else candidate_alerts
    selected_spec_keys = {item[2] for item in selected_alerts_data}

    alerts = []
    for item in candidate_alerts:
        _, payload, spec_key, name, cvr, spec_name, active_students, next_expiry = item
        existing = registry_state.get(spec_key)
        if spec_key in selected_spec_keys:
            alerts.append(payload)
            updated_registry[spec_key] = {
                "name": name,
                "cvr": cvr,
                "specialty": spec_name,
                "last_seen_at": now.isoformat(),
                "last_alerted_at": now.isoformat(),
                "active_students": active_students,
                "next_expiry": next_expiry,
                "alerted_zero_capacity": payload["type"] == "open_capacity"
            }
        else:
            # Deferred alert: preserve existing last_alerted_at so it can be picked up on a future run
            updated_registry[spec_key] = {
                "name": name,
                "cvr": cvr,
                "specialty": spec_name,
                "last_seen_at": now.isoformat(),
                "last_alerted_at": existing.get("last_alerted_at") if existing else None,
                "active_students": active_students,
                "next_expiry": next_expiry,
                "alerted_zero_capacity": existing.get("alerted_zero_capacity", False) if existing else False
            }

    return alerts, updated_registry


def format_radar_telegram_message(alert: dict) -> str:
    """Format a crisp, actionable Telegram alert for accredited learning place insights."""
    name = alert.get("name", "Ukendt")
    city = alert.get("city", "")
    postal = alert.get("postal_code", "")
    spec = alert.get("specialty", "Datatekniker")
    cvr = alert.get("cvr", "")
    igang = alert.get("active_students", 0)
    expiry = alert.get("next_expiry") or "Ingen aktiv elev"
    tip = alert.get("tip", "")

    alert_type = alert.get("type")
    if alert_type == "new_accreditation":
        header = "🏛️ <b>LÆREPLADS RADAR: Nyt Godkendt Lærested!</b>"
    elif alert_type == "contract_expiring":
        header = "⏳ <b>LÆREPLADS RADAR: Elevplads Bliver Snart Ledig!</b>"
    else:
        header = "🎯 <b>LÆREPLADS RADAR: Ledig Kapacitet (Uopfordret)</b>"

    cvr_link = f"https://datacvr.virk.dk/enhed/virksomhed/{cvr}" if cvr else ""
    cvr_str = f'<a href="{cvr_link}">{cvr}</a>' if cvr_link else "N/A"

    area_str = f"{postal} {city}".strip() or "Danmark"
    msg = f"""{header}

🏢 <b>Virksomhed:</b> {name}
📍 <b>Område:</b> {area_str}
🎓 <b>Speciale:</b> {spec}
👥 <b>Aktive elever:</b> {igang}
📅 <b>Næste udløb:</b> {expiry}
📋 <b>CVR:</b> {cvr_str}

💡 <b>Anbefaling:</b>
<i>{tip}</i>
"""
    return msg.strip()
