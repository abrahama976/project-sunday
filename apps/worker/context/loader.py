from pathlib import Path
from config import CONTEXT_FILE_PATH

_cache: str | None = None

def load_profile() -> str:
    global _cache
    path = Path(CONTEXT_FILE_PATH).expanduser()
    if not path.exists():
        return ""
    _cache = path.read_text(encoding="utf-8")
    return _cache

def get_profile() -> str:
    return _cache if _cache is not None else load_profile()
