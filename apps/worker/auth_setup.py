#!/usr/bin/env python3
"""Authorise Google services, once, interactively.

    python3 auth_setup.py            # authorise anything that needs it
    python3 auth_setup.py --force    # re-authorise everything from scratch
    python3 auth_setup.py calendar   # just one service

This is the ONLY place the browser OAuth flow may run. `google_auth` refuses it
everywhere else, because the alternative was seven scheduled jobs each opening
their own consent URL on their own port after a long outage — none completable,
all retrying every minute.

Run it when you are actually at the keyboard. The worker will then find valid
tokens on disk and never need to ask.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import google_auth  # noqa: E402
from google_auth import SERVICES, allow_interactive_auth, get_credentials  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv or "-f" in sys.argv

    targets = args or list(SERVICES)
    unknown = [t for t in targets if t not in SERVICES]
    if unknown:
        print(f"Unknown service(s): {', '.join(unknown)}")
        print(f"Known: {', '.join(SERVICES)}")
        return 2

    allow_interactive_auth()

    if force:
        for name in targets:
            token = Path(__file__).resolve().parent / SERVICES[name]["token_file"]
            if token.exists():
                token.unlink()
                print(f"  removed {token.name}")
        google_auth._cache.clear()

    print("Authorising Google services. A browser window will open for each.")
    print("Expect \"Google hasn't verified this app\" — Advanced → Go to Project")
    print("Sunday (unsafe). That is the unverified-app screen, not an error.\n")

    failed = []
    for name in targets:
        scopes = ", ".join(s.rsplit("/", 1)[-1] for s in SERVICES[name]["scopes"])
        print(f"── {name}  ({scopes})")
        try:
            # One at a time, and only after the previous flow has returned —
            # concurrent consent screens are what this script exists to prevent.
            get_credentials(name)
            print(f"   ✓ {name} authorised\n")
        except Exception as e:
            failed.append(name)
            print(f"   ✗ {name} failed: {e}\n")

    if failed:
        print(f"Still unauthorised: {', '.join(failed)}")
        return 1

    print("All services authorised. Start the worker:  python3 main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
