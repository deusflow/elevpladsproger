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
# Application Specific Configuration
DB_FILE = "jobs_db.json"
# Covers all Region Midtjylland postal codes (6900-6999 Ringkøbing/Skjern, 7130-7180 Hedensted/Juelsminde, 7270-7999 Herning/Holstebro/Skive/Struer/Viborg, 8000-8999 Aarhus/Silkeborg/Horsens/Randers)
TARGET_POSTAL_CODES = (
    set(map(str, range(6900, 7000))) |
    set(map(str, range(7130, 7180))) |
    set(map(str, range(7270, 8000))) |
    set(map(str, range(8000, 9000)))
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

MIDTJYLLAND_CITIES = [
    # Major Cities
    "aarhus", "randers", "silkeborg", "horsens", "herning", 
    "viborg", "holstebro", "skive", "ikast", "brande", 
    "odder", "hinnerup", "skanderborg", "bjerringbro", 
    "hadsten", "hammel", "lemvig", "struer", "grenaa", "ebeltoft",
    "ringkøbing", "ringkoebing", "skjern", "tarm", "videbæk", "videbaek",
    "hedensted", "ry", "galten", "hornslet", "rønde", "roende",
    
    # Aarhus Districts & Tech Hubs
    "viby", "viby j", "brabrand", "tilst", "skejby", "risskov", 
    "højbjerg", "hoejbjerg", "hasselager", "tranbjerg", "lystrup",
    "åbyhøj", "aabyhøj", "aabyhoej", "egå", "egaa", "mårslet", "maarslet",
    "beder", "malling", "solbjerg", "skødstrup", "skoedstrup", "sabro", "trige",
    
    # Region and General Midtjylland terms
    "midtjylland", "østjylland", "oestjylland", "vestjylland", "nordvestjylland",
    "hele landet", "jylland", "remote", "hjemmearbejde"
]

# Strict role keywords
# Only Datatekniker - Programmering & Cybersecurity
TARGET_KEYWORDS = [
    "programmering", "cybersikkerhed", "it-sikkerhed", "cyber security",
    "cybersecurity", "software", "developer", "udvikler", "udvikling"
]

# We want to be sure it's an apprenticeship/elevplads
ELEV_KEYWORDS = ["elev", "lærling", "apprenticeship", "trainee", "elevplads", "læreansættelse"]

EXCLUDE_KEYWORDS = [
    "supporter",
    "supporttekniker",
    "helpdesk",
    "servicedesk",
    "studiejob",
    "student",
    "studentermedhjælper",
    "intern",
    "internship"
]

TARGET_ENTERPRISES = ["arla", "eurowind", "thise mejeri"]

JOB_QUERIES = [
    "datatekniker", "it-elev", "softwareudvikler", "udvikler-elev", "programmering",
    "voksenelev", "voksenlærling", "it-lærling", "eux"
]

# Precompiled Regex Patterns for High Performance
import re
CITY_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, MIDTJYLLAND_CITIES)) + r')\b')
EXCLUSION_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, EXCLUDE_KEYWORDS)) + r')\b')
TARGET_KEYWORD_PATTERN = re.compile(r'\b(?:' + '|'.join(map(re.escape, TARGET_KEYWORDS)) + r')\b')

# RSS Feeds for Danish IT & Startups
RSS_FEEDS = {
    "Version2 News": "https://www.version2.dk/rss",
    "Version2 Blogs": "https://www.version2.dk/blogs/rss",
    "Computerworld": "https://www.computerworld.dk/rss/all",
    "CPH Post Tech": "https://cphpost.dk/category/news/technology/feed/",
    "Videnskab.dk Tech": "https://videnskab.dk/wp-json/rss/v1/feeds?topics=teknologi"
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

