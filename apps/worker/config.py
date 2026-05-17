import os
from pathlib import Path

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_PRO_MODEL = "gemini-2.5-pro"
GEMINI_MAX_TOKENS = 2048
GEMINI_TEMPERATURE = 0.3

OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_HOST = "http://localhost:11434"

HEARTBEAT_INTERVAL_SECONDS = 60
WORKER_RECONNECT_MAX_RETRIES = 5
WORKER_RECONNECT_BACKOFF_BASE_SECONDS = 2
APPROVAL_POLL_INTERVAL_SECONDS = 5
APPROVAL_HOLD_SECONDS = 5

CONTEXT_FILE_PATH = Path.home() / "Projects/PersonalAI/context/user_profile.md"
ALLOWED_WRITE_ROOT = Path.home() / "Projects" / "PersonalAI"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

TOOL_TIER_MAP = {
    "file_read":        "auto",
    "file_list":        "auto",
    "calendar_query":   "auto",
    "gmail_search":     "auto",
    "web_fetch":        "auto",
    "file_write":       "approve",
    "calendar_create":  "approve",
    "gmail_draft":      "approve",
    "update_profile":   "approve",
    "inventory_update": "approve",
    "file_delete":      "hold",
    "gmail_send":       "hold",
    "calendar_delete":  "hold",
    "shell_cmd":        "hold",
}
