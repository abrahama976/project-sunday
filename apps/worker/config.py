import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_LITE_MODEL = "gemini-2.5-flash-lite"
GEMINI_PRO_MODEL = "gemini-2.5-pro"
GEMINI_MAX_TOKENS = 2048
GEMINI_TEMPERATURE = 0.3

OLLAMA_MODEL = "llama3.2:latest"
OLLAMA_HOST = "http://localhost:11434"

# Per-user daily LLM budget limits (tunable)
DAILY_FLASH_LIMIT = 50
DAILY_LITE_LIMIT = 200

HEARTBEAT_INTERVAL_SECONDS = 60
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
