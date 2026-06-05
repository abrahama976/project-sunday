import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_LITE_MODEL = "gemini-2.5-flash-lite"
GEMINI_PRO_MODEL = "gemini-2.5-pro"
# Extended free-tier cascade models
GEMINI_FLASH2_MODEL = "gemini-2.0-flash"     # 1,500 RPD free
GEMINI_FLASH15_MODEL = "gemini-1.5-flash"    # 1,500 RPD free
# Per-user daily limits for new tiers
DAILY_FLASH2_LIMIT = 500
GLOBAL_FLASH2_CEILING = 1000
DAILY_FLASH15_LIMIT = 500
GLOBAL_FLASH15_CEILING = 1000
GEMINI_MAX_TOKENS = 2048
GEMINI_TEMPERATURE = 0.3

OLLAMA_MODEL = "llama3.2:latest"
OLLAMA_HOST = "http://localhost:11434"

# Per-user daily LLM budget limits (tunable)
DAILY_FLASH_LIMIT = 100
GLOBAL_FLASH_CEILING = 200

DAILY_LITE_LIMIT = 300
GLOBAL_LITE_CEILING = 500

HEARTBEAT_INTERVAL_SECONDS = 30
WORKER_RECONNECT_MAX_RETRIES = 5
WORKER_RECONNECT_BACKOFF_BASE_SECONDS = 2
APPROVAL_POLL_INTERVAL_SECONDS = 5
APPROVAL_HOLD_SECONDS = 5

ALLOWED_WRITE_ROOT = Path.home() / "Projects" / "PersonalAI"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
TFNSW_API_KEY = os.environ.get("TFNSW_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
TOOL_TIER_MAP = {
    # File operations
    "file_read":            "auto",
    "file_list":            "auto",
    "file_write":           "approve",
    "file_delete":          "hold",
    # Calendar
    "calendar_query":       "auto",
    "calendar_create":      "approve",
    "calendar_update":      "approve",
    "calendar_delete":      "hold",
    # Gmail
    "gmail_search":         "auto",
    "gmail_read_body":      "auto",
    "gmail_priority_scan":  "auto",
    "gmail_draft":          "approve",
    "gmail_send":           "hold",
    # Tasks
    "task_create":          "auto",
    "task_update":          "auto",
    "task_list":            "auto",
    # Web
    "web_fetch":            "auto",
    "web_search":           "auto",
    # Travel
    "travel_directions":    "auto",
    "transit_departures":   "auto",
    # Profile
    "update_profile":       "approve",
    # Inventory
    "inventory_update":     "approve",
    # Dangerous
    "shell_cmd":            "hold",
}

# ── External integrations ──────────────────────────────────────────────────
TAVILY_API_KEY   = os.getenv("TAVILY_API_KEY", "")
NTFY_TOPIC       = os.getenv("NTFY_TOPIC", "")
NTFY_URL         = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else ""
# Open-Meteo — no key required
USER_LAT         = float(os.getenv("USER_LAT", "-33.8688"))   # Sydney
USER_LNG         = float(os.getenv("USER_LNG", "151.2093"))
USER_TIMEZONE    = os.getenv("USER_TIMEZONE", "Australia/Sydney")
