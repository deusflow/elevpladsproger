import datetime
import logging

logger = logging.getLogger("elevplads_scraper")

# Seed data: Month when hiring typically starts
# 1 = January, 2 = February, etc.
SEED_CYCLES = {
    "arla": [2, 9], # February and September
    "netcompany": [2], # February
    "grundfos": [3], # March
    "vestas": [3], # March
    "lego": [4], # April
    "bestseller": [3], # March
    "jyske bank": [1], # January
    "salling group": [2], # February
    "danske bank": [1], # January
}

def analyze_and_predict(state: dict) -> list[str]:
    """
    Analyzes historical data and seed data to predict upcoming hiring cycles.
    Returns a list of alert messages for companies that are ~30 days away from a hiring wave.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    current_year = now.year
    current_month = now.month
    
    # We want to warn 1 month in advance. 
    # E.g. if now is January, we warn about February.
    target_month = current_month + 1
    if target_month > 12:
        target_month = 1
        
    predictions_sent = state.get("predictions_sent", {})
    
    alerts = []
    
    # Check seed data
    for company, months in SEED_CYCLES.items():
        if target_month in months:
            # Check if we already alerted this year for this month
            alert_key = f"{company}_{current_year}_{target_month}"
            if not predictions_sent.get(alert_key):
                # Map month number to Danish string
                month_names = {
                    1: "januar", 2: "februar", 3: "marts", 4: "april",
                    5: "maj", 6: "juni", 7: "juli", 8: "august",
                    9: "september", 10: "oktober", 11: "november", 12: "december"
                }
                month_name = month_names[target_month]
                alerts.append(
                    f"💡 *Hiring Cycle Predictor*\n"
                    f"🏢 *{company.title()}* plejer historisk at åbne for IT\\-elev/Datatekniker stillinger i {month_name}\\. "
                    f"Det er tid til at forberede dit CV og holde ekstra øje med deres karriereside\\!"
                )
                predictions_sent[alert_key] = True
                
    state["predictions_sent"] = predictions_sent
    return alerts
