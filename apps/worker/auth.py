import subprocess
import os

def get_service_role_key() -> str:
    env_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if env_key:
        return env_key
    result = subprocess.run(
        ["security", "find-generic-password", "-s", "project-sunday-service-role", "-w"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError("Service role key not found in Keychain.")
    return result.stdout.strip()
