import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any
import httpx
import config
from scrapers import format_job, is_valid_job

logger = logging.getLogger("elevplads_scraper")

LAEREPLADSEN_BASE_API = "https://sr.laerepladsen.dk/api/soeg-opslag"
UDDANNELSE_NAME = "Data- og kommunikationsuddannelsen"


async def fetch_laerepladsen_all(max_concurrency: int = 8) -> tuple[list[dict], list[dict]]:
    """Fetch all approved learning places and active postings across Denmark for Data- og kommunikationsuddannelsen.
    Returns:
        (active_jobs, accredited_places_midtjylland)
    """
    udd_encoded = urllib.parse.quote(UDDANNELSE_NAME)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    client_kwargs: dict[str, Any] = {"timeout": 12.0, "follow_redirects": True, "headers": headers}
    if getattr(config, "PROXY_URL", None):
        client_kwargs["proxy"] = config.PROXY_URL

    active_jobs = []
    all_places = []

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            first_url = f"{LAEREPLADSEN_BASE_API}/0/{udd_encoded}/-1"
            resp = await client.get(first_url)
            if resp.status_code != 200:
                logger.error(f"Lærepladsen API returned HTTP {resp.status_code} on initial page")
                return [], []

            data = resp.json()
            total_pages = min(data.get("antalSider", 50), 50)
            all_places.extend(data.get("laeresteder", []))

            sem = asyncio.Semaphore(max_concurrency)

            async def fetch_page(page_num: int):
                async with sem:
                    url = f"{LAEREPLADSEN_BASE_API}/{page_num}/{udd_encoded}/-1"
                    try:
                        r = await client.get(url)
                        if r.status_code == 200:
                            return r.json().get("laeresteder", [])
                    except Exception as e:
                        logger.warning(f"Error fetching Lærepladsen page {page_num}: {e}")
                    return []

            tasks = [fetch_page(p) for p in range(1, total_pages)]
            results = await asyncio.gather(*tasks)
            for items in results:
                all_places.extend(items)

    except Exception as e:
        logger.error(f"Failed to communicate with Lærepladsen API: {e}")
        return [], []

    logger.info(f"Lærepladsen API returned {len(all_places)} total learning places across {total_pages} pages")

    # Filter for Region Midtjylland employers & extract active postings
    accredited_places = []
    seen_opslag_ids = set()

    for place in all_places:
        region = place.get("region", "")
        postal = str(place.get("postnummer", ""))
        is_in_region = ("midt" in region.lower()) or (postal in config.TARGET_POSTAL_CODES)
        if not is_in_region:
            continue

        company_name = place.get("navn", "Ukendt")
        cvr = str(place.get("cvr", ""))
        city = place.get("kommune", "")

        # 1. Process active postings (opslag)
        postings = place.get("opslag", [])
        for op in postings:
            op_id = str(op.get("id", ""))
            if not op_id or op_id in seen_opslag_ids:
                continue
            seen_opslag_ids.add(op_id)

            title = op.get("titel") or op.get("beskrivelse", "")[:60] or "Datateknikerelev"
            direct_url = op.get("kontaktHjemmeside")
            job_url = direct_url if (direct_url and direct_url.startswith("http")) else f"https://laerepladsen.dk/elev/opslag/{op_id}"

            # Enrich job object with direct contact details
            if is_valid_job(title, postal, company_name, location=city, bypass_geo=True):
                job_dict = format_job(
                    job_id=f"laerepladsen_{op_id}",
                    title=title,
                    company=company_name,
                    url=job_url,
                    source="Laerepladsen"
                )
                job_dict["contact_person"] = op.get("kontaktPerson")
                job_dict["contact_phone"] = op.get("kontaktTelefon")
                job_dict["contact_email"] = op.get("kontaktEmail")
                job_dict["deadline"] = op.get("ansoegningsfrist")
                job_dict["start_date"] = op.get("ansaettelsesdato")
                job_dict["description"] = op.get("beskrivelse")
                active_jobs.append(job_dict)

        # 2. Process Datatekniker accreditations
        relevant_approvals = []
        for g in place.get("godkendelser", []):
            spec_name = g.get("speciale", {}).get("navn", "")
            spec_lower = spec_name.lower()
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

    logger.info(f"Lærepladsen Radar identified {len(accredited_places)} Datatekniker accredited employers in Region Midtjylland and {len(active_jobs)} active opslag")
    return active_jobs, accredited_places


def detect_radar_alerts(accredited_places: list[dict], registry_state: dict) -> tuple[list[dict], dict]:
    """Detect high-value unsolicited application opportunities:
    1. Newly accredited companies
    2. Zero active students (open capacity)
    3. Current apprentice contract expiring within 120 days
    """
    alerts = []
    now = datetime.now(timezone.utc)
    updated_registry = registry_state.copy()

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

            # Check for newly accredited learning places
            if is_new_company:
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

                # Check if an apprentice contract is expiring soon (within 30-150 days)
                if can_re_alert and next_expiry:
                    try:
                        exp_dt = datetime.strptime(next_expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
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
                    except Exception:
                        pass

                # Check for approved programming employers with 0 current students (fresh capacity)
                if not alert_payload and can_re_alert and active_students == 0 and "programmering" in spec_name.lower():
                    # Only alert if not actively posting public ads (avoid duplication with job alert)
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

            if alert_payload:
                alerts.append(alert_payload)
                updated_registry[spec_key] = {
                    "name": name,
                    "cvr": cvr,
                    "specialty": spec_name,
                    "last_seen_at": now.isoformat(),
                    "last_alerted_at": now.isoformat(),
                    "active_students": active_students,
                    "next_expiry": next_expiry,
                    "alerted_zero_capacity": alert_payload["type"] == "open_capacity"
                }
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

    return alerts, updated_registry


def format_radar_telegram_message(alert: dict) -> str:
    """Format a crisp, actionable Telegram alert for accredited learning place insights."""
    name = alert.get("name", "Ukendt")
    city = alert.get("city", "Midtjylland")
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

    msg = f"""{header}

🏢 <b>Virksomhed:</b> {name}
📍 <b>Område:</b> {postal} {city}
🎓 <b>Speciale:</b> {spec}
👥 <b>Aktive elever:</b> {igang}
📅 <b>Næste udløb:</b> {expiry}
📋 <b>CVR:</b> {cvr_str}

💡 <b>Anbefaling:</b>
<i>{tip}</i>
"""
    return msg.strip()
