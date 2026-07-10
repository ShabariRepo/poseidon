"""Persistent memory, file school: one markdown file per fact in
~/.poseidon/memory/, plus a MEMORY.md index that is injected into the system
prompt each session. Transparent by design — the user can open, edit, or
delete their agent's memory with a text editor.
"""
import re

from .config import CONFIG_DIR

MEMORY_DIR = CONFIG_DIR / "memory"
INDEX_PATH = MEMORY_DIR / "MEMORY.md"
MAX_MEMORY_READ = 20_000
MAX_INDEX_INJECT = 4_000


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


def save(title: str, content: str) -> dict:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    name = _slug(title)
    path = MEMORY_DIR / f"{name}.md"
    existed = path.exists()
    path.write_text(f"# {title}\n\n{content.strip()}\n")

    hook = content.strip().splitlines()[0][:100] if content.strip() else ""
    entry = f"- [{title}]({name}.md) — {hook}"
    lines = INDEX_PATH.read_text().splitlines() if INDEX_PATH.exists() else []
    lines = [l for l in lines if f"]({name}.md)" not in l]
    lines.append(entry)
    INDEX_PATH.write_text("\n".join(lines) + "\n")
    return {"ok": True, "name": name, "updated": existed}


def read(name: str) -> dict:
    path = MEMORY_DIR / f"{_slug(name)}.md"
    if not path.is_file():
        return {"error": f"no memory named '{name}'"}
    return {"content": path.read_text(errors="replace")[:MAX_MEMORY_READ]}


def forget(name: str) -> dict:
    slug = _slug(name)
    path = MEMORY_DIR / f"{slug}.md"
    if not path.is_file():
        return {"error": f"no memory named '{name}'"}
    path.unlink()
    if INDEX_PATH.exists():
        lines = [l for l in INDEX_PATH.read_text().splitlines() if f"]({slug}.md)" not in l]
        INDEX_PATH.write_text(("\n".join(lines) + "\n") if lines else "")
    return {"ok": True, "forgot": slug}


def load_index() -> str:
    if not INDEX_PATH.exists():
        return ""
    return INDEX_PATH.read_text(errors="replace")[:MAX_INDEX_INJECT]
