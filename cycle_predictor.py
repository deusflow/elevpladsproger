import datetime
import logging

logger = logging.getLogger("elevplads_scraper")

# Seed data: Month when hiring typically starts
# 1 = January, 2 = February, etc.
SEED_CYCLES = {
    "arla": [2, 9], # February and September
    "netcompany": [2, 8], # February and August
    "systematic": [3, 9], # March and September (Aarhus HQ)
    "grundfos": [3, 9], # March and September (Bjerringbro)
    "vestas": [3, 8], # March and August (Aarhus)
    "lego": [3, 10], # March and October (Billund/Midt)
    "bestseller": [2, 8], # February and August (Aarhus/Brande)
    "danske bank": [1, 8], # January and August
    "jyske bank": [1, 8], # January and August (Silkeborg)
    "bankdata": [2, 9], # February and September (Silkeborg/Midt)
    "jn data": [3, 10], # March and October (Silkeborg)
    "bec financial technologies": [2, 9], # February and September
    "kmd": [2, 8], # February and August
    "visma": [3, 9], # March and September (Aarhus)
    "trifork": [2, 8], # February and August (Aarhus)
    "salling group": [2, 8], # February and August (Brabrand)
    "energinet": [2, 9], # February and September
    "stibo systems": [3, 9], # March and September (Aarhus)
}

MONTH_NAMES = {
    1: "januar", 2: "februar", 3: "marts", 4: "april",
    5: "maj", 6: "juni", 7: "juli", 8: "august",
    9: "september", 10: "oktober", 11: "november", 12: "december"
}


def analyze_and_predict(state: dict) -> list[str]:
    """
    Analyzes historical data from state["jobs"] and seed data to predict upcoming hiring cycles.
    Returns a list of alert messages for companies that are ~30 days away from a hiring wave.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    current_year = now.year
    current_month = now.month

    # We want to warn 1 month in advance.
    # E.g. if now is January, we warn about February.
    target_month = current_month + 1
    target_year = current_year
    if target_month > 12:
        target_month = 1
        target_year = current_year + 1

    predictions_sent = state.get("predictions_sent", {})
    month_name = MONTH_NAMES[target_month]
    alerts = []
    alerted_companies = set()

    # 1. Analyze historical jobs from previous years
    historical_jobs = state.get("jobs", [])
    if isinstance(historical_jobs, list):
        for job in historical_jobs:
            if not isinstance(job, dict):
                continue
            company = job.get("company", "").strip()
            discovered_str = job.get("discovered_at")
            if not company or not discovered_str:
                continue

            try:
                discovered_dt = datetime.datetime.fromisoformat(discovered_str)
                # Check if it was discovered in the target month of a previous year
                if discovered_dt.year < current_year and discovered_dt.month == target_month:
                    company_lower = company.lower()
                    alert_key = f"hist_{company_lower}_{target_year}_{target_month}"
                    if not predictions_sent.get(alert_key) and company_lower not in alerted_companies:
                        alerts.append(
                            f"💡 <b>Hiring Cycle Predictor (Historisk data)</b>\n"
                            f"🏢 <b>{company}</b> slog en elevplads op i {month_name} i {discovered_dt.year}. "
                            f"Hold ekstra øje med deres stillinger i den kommende måned!"
                        )
                        predictions_sent[alert_key] = True
                        alerted_companies.add(company_lower)
            except (ValueError, TypeError):
                continue

    # 2. Check seed data (for companies not already alerted)
    for company, months in SEED_CYCLES.items():
        if company in alerted_companies:
            continue
        if target_month in months:
            # Check if we already alerted this year for this month
            alert_key = f"{company}_{target_year}_{target_month}"
            if not predictions_sent.get(alert_key):
                alerts.append(
                    f"💡 <b>Hiring Cycle Predictor</b>\n"
                    f"🏢 <b>{company.title()}</b> plejer historisk at åbne for IT-elev/Datatekniker stillinger i {month_name}. "
                    f"Det er tid til at forberede dit CV og holde ekstra øje med deres karriereside!"
                )
                predictions_sent[alert_key] = True
                alerted_companies.add(company)

    state["predictions_sent"] = predictions_sent
    return alerts
