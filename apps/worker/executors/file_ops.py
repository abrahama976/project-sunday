from pathlib import Path

from config import ALLOWED_WRITE_ROOT


async def file_write(path: str, content: str, append: bool = False) -> str:
    """Write text content to a file with security checks."""
    try:
        p = Path(path).expanduser().resolve()
        
        # Security check: path must be within allowed root
        try:
            p.relative_to(ALLOWED_WRITE_ROOT)
        except ValueError:
            return f"Error: path outside allowed root"
        
        # Security check: reject hidden files and suspicious patterns
        for part in p.parts:
            if part == ".." or part.startswith("."):
                return f"Error: path contains invalid component '{part}'"
        
        # Security check: reject symlinks pointing outside allowed root
        if p.exists() and p.is_symlink():
            try:
                p.resolve(strict=True).relative_to(ALLOWED_WRITE_ROOT)
            except ValueError:
                return f"Error: symlink target outside allowed root"
        
        # Create parent directories if needed
        p.parent.mkdir(parents=True, exist_ok=True)
        
        # Write or append
        if append:
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
        else:
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        
        # Return success
        bytes_written = len(content.encode("utf-8"))
        return f"Wrote {bytes_written} bytes to {p}"
    
    except Exception as e:
        return f"Error: {str(e)}"


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
