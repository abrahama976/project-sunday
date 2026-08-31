"""Centralised Google OAuth2 credential management.

All Google API executors import `get_credentials(service_name)` from here
instead of duplicating the OAuth flow. Supports Calendar, Gmail, and future
Google services.
"""
import asyncio
import threading
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

_WORKER_DIR = Path(__file__).resolve().parent
_CREDENTIALS_PATH = _WORKER_DIR / "credentials.json"


class ReauthRequired(RuntimeError):
    """No usable credentials, and we are not allowed to prompt for them here.

    Raised instead of opening a browser when running unattended. Callers should
    let this propagate: the job fails with a clear message, and the user runs
    `python3 auth_setup.py` once when they are actually at the keyboard.
    """


# Only an explicit, interactive entry point may run the browser flow.
# Everything else — scheduled jobs, chat tool calls, the poll loops — is
# unattended by definition.
#
# This exists because of a real incident: a worker starting after a 60-day
# outage fired seven catch-up jobs at once, and each one independently called
# InstalledAppFlow.run_local_server(port=0). Seven consent URLs on seven ports,
# none of them completable, retrying every minute. The fix is not to serialise
# those flows — it is that none of them should have existed.
_interactive_auth_allowed = False

# Guards the one flow that IS allowed, in case two threads reach it together.
_auth_lock = threading.Lock()


def allow_interactive_auth() -> None:
    """Permit the browser OAuth flow on this process. Call only from a CLI."""
    global _interactive_auth_allowed
    _interactive_auth_allowed = True

# ── Service definitions ────────────────────────────────────────
SERVICES: dict[str, dict] = {
    "calendar": {
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "token_file": "token_calendar.json",
    },
    "gmail": {
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "token_file": "token_gmail.json",
    },
}

# In-memory credential cache keyed by service name
_cache: dict[str, Credentials] = {}


def get_credentials(service_name: str) -> Credentials:
    """Return valid OAuth2 credentials for the given service.
    
    On first call, loads from token file or triggers browser auth flow.
    Caches credentials in memory and refreshes automatically when expired.
    
    Raises:
        ValueError: If service_name is not registered in SERVICES.
        FileNotFoundError: If credentials.json is missing.
        RuntimeError: If token refresh fails (e.g. revoked).
    """
    if service_name not in SERVICES:
        raise ValueError(
            f"Unknown Google service '{service_name}'. "
            f"Known services: {', '.join(SERVICES)}"
        )

    service = SERVICES[service_name]
    scopes = service["scopes"]
    token_path = _WORKER_DIR / service["token_file"]

    # Check memory cache first
    if service_name in _cache:
        creds = _cache[service_name]
        if creds.valid:
            return creds
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                return creds
            except Exception as e:
                print(f"[google_auth] token refresh failed for {service_name}: {e}")
                # Fall through to re-auth
                del _cache[service_name]

    # Load from disk
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception as e:
            print(f"[google_auth] failed to load token file for {service_name}: {e}")

    if creds and creds.valid:
        _cache[service_name] = creds
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            _cache[service_name] = creds
            return creds
        except Exception as e:
            print(f"[google_auth] refresh failed for {service_name}, re-authenticating: {e}")

    # Full OAuth flow — requires a human at a browser.
    if not _interactive_auth_allowed:
        raise ReauthRequired(
            f"Google {service_name} needs re-authorisation and this process "
            "cannot prompt for it. Run:  python3 auth_setup.py"
        )

    if not _CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {_CREDENTIALS_PATH}. "
            "Download it from Google Cloud Console."
        )

    with _auth_lock:
        # Re-check inside the lock: another thread may have completed the flow
        # for this service while we were waiting, and a second consent screen
        # for credentials we now hold is pure confusion.
        if service_name in _cache and _cache[service_name].valid:
            return _cache[service_name]

        flow = InstalledAppFlow.from_client_secrets_file(
            str(_CREDENTIALS_PATH), scopes
        )
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        _cache[service_name] = creds
        return creds


def verify_all_tokens() -> dict[str, bool]:
    """Check validity of all registered service tokens on startup.
    
    Returns a dict of {service_name: is_valid}. Does NOT trigger re-auth.
    """
    results = {}
    for name, service in SERVICES.items():
        token_path = _WORKER_DIR / service["token_file"]
        if not token_path.exists():
            results[name] = False
            continue
        try:
            creds = Credentials.from_authorized_user_file(
                str(token_path), service["scopes"]
            )
            if creds.valid:
                results[name] = True
            elif creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                _cache[name] = creds
                results[name] = True
            else:
                results[name] = False
        except Exception:
            results[name] = False
    return results
