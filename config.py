import os
import sys
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


def validate_config(mode: str = "all", skip_in_tests: bool = True) -> None:
    """Fail-fast verification of mandatory environment variables at application startup."""
    if skip_in_tests and ("unittest" in sys.modules or "pytest" in sys.modules):
        return

    required = {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_KEY": SUPABASE_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        logger.critical(
            f"FAIL-FAST: Missing mandatory environment variables: {', '.join(missing)}. "
            "Please ensure they are configured in your environment or GitHub Secrets."
        )
        sys.exit(1)

# Playwright / HTTPX Proxy Configuration
PROXY_URL = os.getenv("PROXY_URL")

# Application Specific Configuration
DB_FILE = "jobs_db.json"
TARGET_COMPANIES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "target_companies.json")

# Geographic scope: search ALL of Jutland + Funen (Region Midtjylland, Region
# Nordjylland and Region Syddanmark) while still excluding Zealand/Copenhagen
# and Bornholm (postal codes 1000-4999 / 37xx).
TARGET_REGIONS = ["Midtjylland", "Nordjylland", "Syddanmark"]

# URL slugs used by Jobindex (jobsoegning/it/<slug>) and IT-Jobbank
# (jobsoegning/<slug>) — verified live, both sites use the same scheme.
TARGET_REGION_SLUGS = ["region-midtjylland", "region-nordjylland", "region-syddanmark"]

# Postal ranges: Danish postal codes are geographically ordered. 5000-9999
# covers exactly Fyn (Region Syddanmark) + all of Jutland (the three target
# regions). Anything from Zealand/Hovedstaden (1000-4999) is excluded.
TARGET_REGION_POSTAL_RANGES = [
    (5000, 6000),   # Region Syddanmark – Fyn & Langeland (Odense 5000, Svendborg 5700, ...)
    (6000, 7000),   # Sønderjylland (Kolding 6000, Esbjerg 6700, Varde 6800) + west-Midtjylland
    (7000, 9000),   # Vejle 7100, Billund 7190, Herning 7400, Viborg 8800, Aarhus 8000, ...
    (9000, 10000),  # Region Nordjylland – Aalborg 9000, Hjørring 9800, Skagen 9990, ...
]
TARGET_POSTAL_CODES = set(
    str(code)
    for start, end in TARGET_REGION_POSTAL_RANGES
    for code in range(start, end)
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# User Profile for personalized Cover Letter generation & Scoring
USER_PROFILE = """
Oleh Reznychenko
Data Technician Apprentice – Specialization in Programming

SUMMARY
Building systems that users actually want to use every day is my approach to learning. As a Data Technician apprentice, I run an automated news bot with 300+ daily users, developed in Go, C#, and GitHub Actions. My goal now is to find a permanent employer in Denmark where I can keep growing as a developer and contribute to real production systems.

KOMPETENCER
• Programmering: Go, C#, SQL, Python
• DevOps og cloud: Docker, GitHub Actions, CI/CD, VPS
• IT Security & Networking: Cybersecurity, Active Directory, SSH, DNS
• Languages: Danish, English, Ukrainian/Russian (native), Polish
• Frameworks & Tools: ASP.NET Core, FastAPI, Hugo

EDUCATION
Mercantec, Viborg 8800, Danmark
Datateknikker – Programmering (forventet afslutning: Juni 2029.)
• GF2 – Data og kommunikation (afsluttet januar 2025)

PROJECTS
1. Hotel Management System (H2 Project) Full-stack .NET 9 solution focused on backend architecture and security.
• Backend: REST API in ASP.NET Core, JWT, BCrypt, RBAC.
• Database: Entity Framework Core.
• DevOps: Docker Compose.

2. Automated News Platform (Telegram + Web)
• Backend in Go: RSS ingestion, HTML scraping, API integration
• AI pipeline: translation, summarization, structured output
• Database: PostgreSQL & Supabase
• DevOps: CI/CD (GitHub Actions)

WORK EXPERIENCE
Mercantec (elev) Danmark
Data Technician – Programming Specialization (February 2025 – Present)
• Core focus: C# Development, Automation, and Database Structures.
• Built a production-ready news aggregation bot.
"""

COVER_LETTER_TEMPLATE = """
Datatekniker-elev med speciale i programmering søger elevplads i Danmark 

Oleh Reznychenko 
Viborg | 50 30 21 70 | deusflow@proton.me| linkedin.com/in/deusflow | deusflow.github.io/curriculumvitae 

Hej [Contact Person/Team] hos [Company Name], 

[Opening hook: E.g., Jeg søger hermed stillingen som programmørelev hos jer, fordi...]

Jeg har afsluttet GF2 som datatekniker med speciale i programmering og er i øjeblikket i praktik på Mercantecs skoleoplæringscenter, mens jeg søger en fast elevplads. Jeg lærer bedst, når jeg bygger ting, der rent faktisk bliver brugt, ikke kun til eksamen. 

Et godt eksempel er min automatiserede nyhedsplatform: en bot der indsamler, opsummerer og publicerer indhold på tværs af Telegram og web via et CI/CD-setup med GitHub Actions, Go i backend og PostgreSQL til datahåndtering. Den bruges i dag af 400+ daglige brugere og kører uden manuel indgriben. For mig er det et bevis på, at jeg kan tage et projekt fra idé til produktion. 

Det, der tiltrækker mig ved netop denne elevplads hos [Company Name], er [Specific reason related to the job description]. 

Jeg er klar til samtale når det passer jer og ser frem til at høre fra jer. 

De bedste hilsner  
Oleh Reznychenko 
"""

# Cities / area names accepted as "in scope" when a listing has no postal code.
# Covers Region Midtjylland, Region Nordjylland and Region Syddanmark.
TARGET_CITIES = [
    # Major Cities – Midtjylland
    "aarhus", "randers", "silkeborg", "horsens", "herning", 
    "viborg", "holstebro", "skive", "ikast", "brande", 
    "odder", "hinnerup", "skanderborg", "bjerringbro", 
    "hadsten", "hammel", "lemvig", "struer", "grenaa", "ebeltoft",
    "ringkøbing", "ringkoebing", "skjern", "tarm", "videbæk", "videbaek",
    "hedensted", "ry", "galten", "hornslet", "rønde", "roende", "billund",
    
    # Aarhus Districts & Tech Hubs
    "viby", "viby j", "brabrand", "tilst", "skejby", "risskov", 
    "højbjerg", "hoejbjerg", "hasselager", "tranbjerg", "lystrup",
    "åbyhøj", "aabyhøj", "aabyhoej", "egå", "egaa", "mårslet", "maarslet",
    "beder", "malling", "solbjerg", "skødstrup", "skoedstrup", "sabro", "trige",
    
    # Region Nordjylland
    "aalborg", "nørresundby", "norresundby", "hjørring", "hjorring",
    "frederikshavn", "skagen", "sindal", "sæby", "saeby", "brønderslev",
    "bronderslev", "dronninglund", "hirtshals", "løkken", "loekken",
    "aars", "hobro", "hadsund", "støvring", "stovring", "farsø",
    "thisted", "hanstholm", "nykøbing m", "nykøbing mors", "hurup",
    "vendsyssel", "himmerland", "nordjylland", "north jutland",
    
    # Region Syddanmark – Fyn
    "odense", "svendborg", "nyborg", "middelfart", "assens", "faaborg",
    "fyn", "funen", "nordfyn", "sydfyn", "langeland", "bogense",
    
    # Region Syddanmark – Southern Jutland
    "vejle", "kolding", "fredericia", "haderslev", "aabenraa",
    "sønderborg", "sonderborg", "gråsten", "graasten", "padborg", "tønder",
    "tonder", "ribe", "vejen", "varde", "oksbøl", "oksbol", "esbjerg",
    "rødekro", "roedekro", "christiansfeld", "nordborg", "broager",
    "sydjylland", "south jutland", "sønderjylland", "sonderjylland", "syddanmark",
    
    # General region terms
    "midtjylland", "østjylland", "oestjylland", "vestjylland", "nordvestjylland",
    "hele landet", "jylland", "remote", "hjemmearbejde"
]

# Backwards-compatible alias (older code/tests refer to the Midtjylland list).
MIDTJYLLAND_CITIES = TARGET_CITIES

# Strict role keywords
# Datatekniker - Programmering, Software & Cybersecurity
TARGET_KEYWORDS = [
    "programmering", "cybersikkerhed", "it-sikkerhed", "cyber security",
    "cybersecurity", "software", "developer", "udvikler", "udviklerelev",
    "softwareudvikling", "webudvikling", "appudvikling", "datatekniker",
    "datafaglig", "fullstack", "frontend", "backend", "cloud", "devops",
    "kodning", "data engineering", "programming"
]

# We want to be sure it's an apprenticeship/elevplads (Danish & English variants)
ELEV_KEYWORDS = [
    "elev", "lærling", "apprentice", "apprenticeship", "trainee",
    "elevplads", "læreansættelse", "voksenelev", "voksenlærling",
    "skoleoplæring", "oplæringsvirksomhed", "datafaglig elev"
]

EXCLUDE_KEYWORDS = [
    "supporter",
    "supporttekniker",
    "helpdesk",
    "servicedesk",
    "studiejob",
    "student",
    "studentermedhjælper",
    "internship",
    "ulønnet praktikant",
    "ulønnet"
]

# ---------------------------------------------------------------------------
# Role specialisation classification
# ---------------------------------------------------------------------------
# The project tracks the "Data- og kommunikationsuddannelsen" (Datatekniker)
# family, EXCLUDING the It-supporter specialisation, with the main focus on
# Datatekniker - Programmering. These lists drive both filtering and ranking.

# Top priority: programming / software development
# NOTE: these are matched as substrings (see scrapers.job_priority) so that
# forms like "Programmørelev" or "Softwareudvikler" are recognised.
PROGRAMMING_KEYWORDS = [
    "programm", "software", "developer", "fullstack", "full-stack",
    "frontend", "front-end", "backend", "back-end", "webudvikl", "app-udvikl",
    "kodning", "kode", "data engineer", "database", "sql", "python", "c#",
    ".net", "java", "typescript",
    # Strong Danish compound-only stems: bare "udvikl" would wrongly rank ANY
    # ad with the generic Danish verb "udvikle" (e.g. "Vil du være med til at
    # udvikle skoleledergruppen?") as programming, so keep the technical/
    # elev compounds explicitly instead.
    "udviklerelev", "softwareudvikling", "webudvikling", "appudvikling",
    "software udvikling",
]

# Secondary focus: cybersecurity / IT-security (still a Datatekniker speciale)
SECURITY_KEYWORDS = [
    "cyber", "sikkerhed", "security", "infosec", "penetration", "pentest",
    "ethical hack", "hacking",
]

# Lower priority: Datatekniker infrastructure / operations
INFRA_KEYWORDS = [
    "infrastruktur", "infrastructure", "drift", "netværk", "netvaerk",
    "network", "server", "cloud", "virtualisering", "virtualization",
    "sysadmin", "systemadministrator", "devops", "data center", "datacenter",
]

# If a title contains any of these substrings, a "support"-like word does NOT
# disqualify it (e.g. "Elev til IT-support og softwareudvikling").
ROLE_OVERRIDE_KEYWORDS = [
    "datatekniker", "programm", "software", "udvikl", "cyber", "sikkerhed",
    "kode", "developer", "security",
]

TARGET_ENTERPRISES = ["arla", "eurowind", "thise mejeri"]

JOB_QUERIES = [
    # Danish core technical queries
    "datatekniker", "datateknikerelev", "it-elev", "programmørelev", "udvikler-elev",
    "software elev", "elev programmering", "it-lærling", "voksenelev it", "elevplads it",
    # English queries for international employers in Denmark (LEGO, Grundfos, Vestas, etc.)
    "software apprentice", "it apprentice", "developer apprentice", "apprentice software"
]

# Word-boundary aware pattern for matching apprenticeship signals in AD BODIES
# (scrapers.is_valid_job extra_text). PILOT USE ONLY in titles: titles are
# matched as plain substrings, but bodies contain many words that must NOT
# create an apprenticeship signal:
#   - English "relevant" embeds the Danish stem "elev" (r-e-l-e-v-a-n-t).
#   - Danish "elever"/"eleverne" describes a school's pupils — virtually every
#     school/municipal/teacher ad mentions them without offering an elevplads.
#   - "datatekniker" in a body usually lists a REQUIRED education for a regular
#     senior role, not an offer of an apprenticeship.
# So body scans only accept explicit apprenticeship wording. Titles are short
# and curated, so the substring list (ELEV_KEYWORDS) stays in play there.
    # NOTE: bare "trainee" is deliberately NOT a body signal: English benefit
    # sections mention "grants for trainees" for regular senior roles. A real
    # English-language trainee vacancy carries "trainee" in its TITLE instead.
ELEV_BODY_KEYWORDS = [
    "elevplads", "elevpladserne", "lærlingeplads", "lærlingepladser",
    "lærlingekontrakt", "lærlingeforhold", "lærlingekontoret",
    "læreansættelse", "lærekontrakt", "elevkontrakt", "elevstilling",
    "apprentice", "apprenticeship",
    "voksenelev", "voksenlærling", "skoleoplæring", "oplæringsvirksomhed",
    "datateknikerelev",
]

# Precompiled Regex Patterns for High Performance
import re
CITY_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, TARGET_CITIES)) + r')\b')
EXCLUSION_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, EXCLUDE_KEYWORDS)) + r')\b')
# NOTE: "\bsupport" also matches "supporter", "supporttekniker", "supporting" etc.
# so pure support/helpdesk/service-desk roles are reliably caught. This is the
# core "Datatekniker except IT-support" requirement.
SUPPORT_EXCLUSION_PATTERN = re.compile(
    r'\b(?:support|helpdesk|service\s*desk|servicedesk|brugerstøtte)', re.IGNORECASE
)
HARD_EXCLUSION_PATTERN = re.compile(r'\b(?:studiejob|studentermedhjælper|ulønnet praktikant|ulønnet)\b', re.IGNORECASE)
TARGET_KEYWORD_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, TARGET_KEYWORDS)) + r')\b')

# Word-boundary aware variant of the body keywords above. Most body keywords
# get a leading word boundary plus a small set of Danish inflection suffixes
# (elevpladsen, lærlingepladser, apprentices, trainees ...). The stems
# "elevplads" and "lærlingeplads" allow ANY continuation, because only Danish
# apprenticeship vocabulary forms compounds with them (elevpladskandidat ...).
def _dk_body_keyword(keyword: str) -> str:
    if keyword in ("elevplads", "lærlingeplads", "elevkontrakt"):
        return r'\b' + re.escape(keyword) + r'\w*\b'
    return r'\b' + re.escape(keyword) + r'(?:ernes|erne|erens|ens|ene|en|es|er|e|s)?\b'

ELEV_BODY_PATTERN = re.compile('|'.join(_dk_body_keyword(k) for k in ELEV_BODY_KEYWORDS))

# Curated High-Value IT, Engineering, Architecture, Hardware & Danish Tech RSS Feeds
RSS_FEEDS = {
    # 1. Systems Engineering, Linux Kernel, Compilers, DBs, Architecture
    "Phoronix": "https://www.phoronix.com/phoronix-rss.php",
    "Hacker News Frontpage": "https://hnrss.org/frontpage",
    "Lobste.rs": "https://lobste.rs/rss",
    "GitHub Engineering": "https://github.blog/feed/",
    
    # 2. Hardware, Semiconductors, CPUs, GPUs & Breakthrough Tech
    "Tom's Hardware": "https://www.tomshardware.com/feeds/all",
    "The Verge Tech": "https://www.theverge.com/rss/index.xml",
    "Ars Technica": "https://arstechnica.com/feed/",
    "Engadget": "https://www.engadget.com/rss.xml",
    "TechCrunch": "https://techcrunch.com/feed/",
    
    # 3. Infosec & Cybersecurity
    "BleepingComputer": "https://www.bleepingcomputer.com/feed/",
    
    # 4. 3D Graphics, GameDev & WebGPU Tech
    "80.lv Game & 3D Tech": "https://80.lv/feed/",
    
    # 5. Danish IT, Research & Industry
    "Version2 News": "https://www.version2.dk/rss",
    "Version2 Blogs": "https://www.version2.dk/blogs/rss",
    "Computerworld": "https://www.computerworld.dk/rss/all",
    "Videnskab.dk Tech": "https://videnskab.dk/wp-json/rss/v1/feeds?topics=teknologi",
    "DR Viden": "https://www.dr.dk/nyheder/service/feeds/viden"
}

TECH_TERMS_POOL = [
    "OSI-модель", "TCP vs UDP", "CORS", "JWT", "HTTPS/TLS", "DNS", "SSH", "IP-адрес vs MAC-адрес", 
    "VPN", "Proxy", "Firewall", "Load Balancer", "DDoS-атака", "Phishing", "Ransomware", "Zero-day",
    "REST", "Dependency Injection (DI)", "SOLID", "CAP-теорема", "Микросервисы vs Монолит", "MVC", 
    "Pub/Sub", "Event-Driven Architecture", "Serverless", "API Gateway", "GraphQL", "WebSockets", "gRPC",
    "ACID", "База данных vs Таблица", "Индексы в БД", "Реляционные vs NoSQL БД", "Кэширование (Redis/Memcached)", 
    "SQL-инъекция", "Транзакции", "Нормализация БД", "Sharding", "Replication",
    "Docker", "Kubernetes", "CI/CD", "Git", "Linux kernel", "DNS-записи", "Virtual Machines vs Containers", 
    "Reverse Proxy (Nginx)", "Infrastructure as Code (IaC)", "Terraform", "Ansible",
    "Big O нотация", "Стековый кадр (Stack vs Heap)", "Garbage Collection (Сборка мусора)", "Идемпотентность", 
    "Сериализация данных (JSON/Protobuf)", "Хэширование", "Симметричное vs Асимметричное шифрование", 
    "Race Condition", "Deadlock", "Асинхронное программирование (Async/Await)", "Многопоточность (Multithreading)"
]

