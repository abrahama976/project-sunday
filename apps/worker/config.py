import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_LITE_MODEL = "gemini-2.5-flash-lite"
GEMINI_PRO_MODEL = "gemini-2.5-pro"
# Extended free-tier cascade models
GEMINI_FLASH2_MODEL = "gemini-2.0-flash"     # 1,500 RPD free
GEMINI_FLASH15_MODEL = "gemini-2.0-flash-lite"    # 1,500 RPD free
# Per-user daily limits for new tiers
DAILY_FLASH2_LIMIT = 500
GLOBAL_FLASH2_CEILING = 1000
DAILY_FLASH15_LIMIT = 500
GLOBAL_FLASH15_CEILING = 1000
# Thinking tokens are drawn from this same allowance on the 2.5 models, and
# they are spent BEFORE any visible output. At 2048, a question needing a
# couple of reasoning steps against ~20 tool declarations could burn the lot
# and return a candidate with no parts at all — which the loop then reported
# as "I couldn't complete that request with the current budget" on a day with
# 4 requests used out of 100. The free tier is gated on requests per day, not
# tokens, so a higher ceiling costs nothing against the 250/day cap.
GEMINI_MAX_TOKENS = 8192
GEMINI_TEMPERATURE = 0.3

OLLAMA_MODEL = "llama3.2:latest"
OLLAMA_HOST = "http://localhost:11434"

# Per-user daily LLM budget limits (tunable)
DAILY_FLASH_LIMIT = 100
GLOBAL_FLASH_CEILING = 200

DAILY_LITE_LIMIT = 300
GLOBAL_LITE_CEILING = 500

# ── Agentic loop ───────────────────────────────────────────────────────────
# Maximum think→act→observe rounds in a single user turn. Each round is a
# model call against the same 250/day budget as conversation, so this is a
# spend ceiling as much as a runaway guard. Five covers the chains that
# actually come up (calendar → travel, gmail search → read → draft).
MAX_TOOL_ITERS = 5

# ── Learning brain ─────────────────────────────────────────────────────────
# Learned directives ride in the system prompt on EVERY request, so these caps
# are a budget control as much as a quality one: 40 rules at ~120 chars is
# roughly 1.5k tokens on all 250 daily requests. Raise deliberately.
BRAIN_MAX_DIRECTIVES = 40
BRAIN_MAX_CHARS = 6000
# The summariser proposes at most this many inferred directives per run, so a
# single chatty conversation cannot flood the approvals queue.
BRAIN_MAX_PROPOSALS_PER_RUN = 2

# Minutes of slack built into a leave-by time. Your choice; some people want
# 15. It is the difference between a calm walk to the stop and a run.
TRAVEL_BUFFER_MINUTES = 5

# ── The local network ──────────────────────────────────────────────────────
# How far to walk to reach a boarding point, by what you would be boarding.
# Different numbers because people behave differently: a 20-minute walk to a
# metro is normal and a 20-minute walk to a bus stop is not, when a closer stop
# runs the same service.
WALK_RADIUS_BUS_M = 800
WALK_RADIUS_RAIL_M = 2000

# Boarding points evaluated per trip, chosen for VARIETY rather than proximity
# — one stop per distinct route. Five nearest stops would otherwise be five
# stops on the same road served by the same bus, which is the failure this
# whole mechanism exists to fix. Each is one concurrent TfNSW query.
BOARDING_POINT_LIMIT = 5

# The car is for once in a while, so park-and-ride has to clear a bar rather
# than appear routinely: it must beat the best transit option by this much
# before it is worth mentioning at all.
PARK_RIDE_MIN_SAVING_MIN = 10
# How far it is worth driving to reach a station.
PARK_RIDE_RADIUS_M = 5000

HEARTBEAT_INTERVAL_SECONDS = 30
WORKER_RECONNECT_MAX_RETRIES = 5
WORKER_RECONNECT_BACKOFF_BASE_SECONDS = 2
APPROVAL_POLL_INTERVAL_SECONDS = 5
APPROVAL_HOLD_SECONDS = 5

ALLOWED_WRITE_ROOT = Path.home() / "Projects" / "PersonalAI"

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# OpenRouteService replaced Google Maps: the Directions API refuses every
# request without a billing account attached, which this project will not
# have. ORS is key-only with no card, 2000 directions/day, and returns 403
# at the cap rather than a bill.
OPENROUTESERVICE_API_KEY = os.environ.get("OPENROUTESERVICE_API_KEY", "")
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
    "trip_plan":            "auto",
    "leave_by":             "auto",
    "nearby_services":      "auto",
    # Profile & memory
    "update_profile":       "approve",
    "brain_learn":          "approve",
    # Reminders
    "schedule_reminder":    "approve",
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
