from pathlib import Path

async def file_read(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise ValueError(f"Path is not a file: {p}")
    return p.read_text(encoding="utf-8")

async def file_list(path: str) -> str:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {p}")
    entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
    lines = [f"{'[DIR] ' if e.is_dir() else '[FILE]'} {e.name}" for e in entries]
    return "\n".join(lines)
