from pathlib import Path
from config import CONTEXT_FILE_PATH
from context.loader import load_profile

async def update_profile(section: str, content: str) -> str:
    path = Path(CONTEXT_FILE_PATH).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    addition = f"\n\n## {section}\n{content}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(addition)
    load_profile()
    return f"Profile updated: added section '{section}'"
