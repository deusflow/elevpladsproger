import os
import logging

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("elevplads_scraper")

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Playwright / HTTPX Proxy Configuration
PROXY_URL = os.getenv("PROXY_URL")

# Application Specific Configuration
DB_FILE = "jobs_db.json"
TARGET_POSTAL_CODES = set(map(str, range(7400, 9000)))

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

MIDTJYLLAND_CITIES = [
    "aarhus", "randers", "silkeborg", "horsens", "herning", 
    "viborg", "holstebro", "skive", "ikast", "brande", 
    "odder", "hinnerup", "skanderborg", "bjerringbro", 
    "hadsten", "hammel", "lemvig", "struer", "grenaa", "ebeltoft"
]


# Strict role keywords
# Only Datatekniker - Programmering & Cybersecurity
TARGET_KEYWORDS = [
    "programmering", "cybersikkerhed", "it-sikkerhed", "cyber security",
    "cybersecurity", "software", "developer", "udvikler", "udvikling"
]

# We want to be sure it's an apprenticeship/elevplads
ELEV_KEYWORDS = ["elev", "lærling", "apprenticeship"]

EXCLUDE_KEYWORDS = [
    "supporter",
    "infrastruktur",
    "support",
    "drift",
    "helpdesk",
    "studiejob",
    "student",
    "studentermedhjælper",
    "intern",
    "internship",
    "netværk"
]

TARGET_ENTERPRISES = ["arla", "eurowind", "thise mejeri"]
