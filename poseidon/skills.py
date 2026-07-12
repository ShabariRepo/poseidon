"""Skills: reusable how-to instructions as markdown, agentskills.io-style.
Global: ~/.poseidon/skills/<name>.md or <name>/SKILL.md
Project: <workdir>/.poseidon/skills/...
Frontmatter (optional): name: / description: lines. The index goes in the
system prompt; use_skill loads the full text on demand.
"""
import re
from pathlib import Path

from .config import CONFIG_DIR

MAX_SKILL = 24_000


def _iter_files(workdir: Path):
    for base in (CONFIG_DIR / "skills", workdir / ".poseidon" / "skills"):
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.is_file() and p.suffix == ".md":
                yield p.stem, p
            elif p.is_dir() and (p / "SKILL.md").is_file():
                yield p.name, p / "SKILL.md"


def _meta(text: str, fallback: str):
    name = fallback
    desc = ""
    m = re.search(r"^name:\s*(.+)$", text[:2000], re.M)
    if m:
        name = m.group(1).strip()
    m = re.search(r"^description:\s*(.+)$", text[:2000], re.M)
    if m:
        desc = m.group(1).strip()
    if not desc:
        for ln in text.splitlines():
            ln = ln.strip()
            if ln and not ln.startswith(("---", "#", "name:", "description:")):
                desc = ln[:160]
                break
    return name, desc


def list_skills(workdir: Path) -> list:
    out, seen = [], set()
    for stem, path in _iter_files(workdir):
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        name, desc = _meta(text, stem)
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name, "description": desc, "path": str(path)})
    return out[:40]


def read_skill(workdir: Path, name: str) -> dict:
    for skill in list_skills(workdir):
        if skill["name"].lower() == name.strip().lower():
            return {"content": Path(skill["path"]).read_text(errors="replace")[:MAX_SKILL]}
    return {"error": f"no skill named '{name}'"}
