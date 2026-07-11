"""Persistent memory: an Obsidian-compatible vault per project (team-shared).
One markdown file per fact in ~/.poseidon/memory/<project>/, [[wikilinks]]
between related facts, MEMORY.md index injected into the system prompt.
The graph is parsed from the links — recall follows them (1 hop) so related
facts surface together. Transparent by design: open the folder in any editor,
or in Obsidian itself for the full graph view.
"""
import re

from .config import CONFIG_DIR

MAX_MEMORY_READ = 20_000
MAX_INDEX_INJECT = 4_000
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")


def extract_links(text: str) -> list:
    return [m.strip() for m in WIKILINK.findall(text or "")]


def _dir(project_id: str):
    return CONFIG_DIR / "memory" / (project_id or "default")


def _index_path(project_id: str):
    return _dir(project_id) / "MEMORY.md"


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "untitled"


def save(project_id: str, title: str, content: str) -> dict:
    d = _dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    name = _slug(title)
    path = d / f"{name}.md"
    existed = path.exists()
    path.write_text(f"# {title}\n\n{content.strip()}\n")
    hook = content.strip().splitlines()[0][:100] if content.strip() else ""
    entry = f"- [{title}]({name}.md) — {hook}"
    idx = _index_path(project_id)
    lines = idx.read_text().splitlines() if idx.exists() else []
    lines = [l for l in lines if f"]({name}.md)" not in l]
    lines.append(entry)
    idx.write_text("\n".join(lines) + "\n")
    return {"ok": True, "name": name, "updated": existed}


def read(project_id: str, name: str) -> dict:
    path = _dir(project_id) / f"{_slug(name)}.md"
    if not path.is_file():
        return {"error": f"no memory named '{name}'"}
    content = path.read_text(errors="replace")[:MAX_MEMORY_READ]
    # associative recall: follow wikilinks one hop
    linked = []
    for title in extract_links(content)[:6]:
        lp = _dir(project_id) / f"{_slug(title)}.md"
        if lp.is_file():
            ltext = lp.read_text(errors="replace")
            linked.append({"title": title, "content": ltext[:1200]})
    return {"content": content, "linked": linked}


def forget(project_id: str, name: str) -> dict:
    slug = _slug(name)
    path = _dir(project_id) / f"{slug}.md"
    if not path.is_file():
        return {"error": f"no memory named '{name}'"}
    path.unlink()
    idx = _index_path(project_id)
    if idx.exists():
        lines = [l for l in idx.read_text().splitlines() if f"]({slug}.md)" not in l]
        idx.write_text(("\n".join(lines) + "\n") if lines else "")
    return {"ok": True, "forgot": slug}


def load_index(project_id: str) -> str:
    idx = _index_path(project_id)
    if not idx.exists():
        return ""
    return idx.read_text(errors="replace")[:MAX_INDEX_INJECT]


def list_entries(project_id: str) -> list:
    d = _dir(project_id)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.md")):
        if f.name == "MEMORY.md":
            continue
        text = f.read_text(errors="replace")
        title = text.splitlines()[0].lstrip("# ").strip() if text else f.stem
        out.append({"name": f.stem, "title": title, "preview": text[:400],
                    "links": extract_links(text)})
    return out


def graph(project_id: str) -> dict:
    """The brain: nodes = memories, edges = wikilinks. Ghost nodes for links
    that don't resolve yet (they mark something worth writing)."""
    entries = list_entries(project_id)
    slugs = {e["name"] for e in entries}
    nodes = [{"id": e["name"], "title": e["title"], "ghost": False} for e in entries]
    edges, ghosts = [], set()
    for e in entries:
        for title in e["links"]:
            target = _slug(title)
            if target not in slugs and target not in ghosts:
                ghosts.add(target)
                nodes.append({"id": target, "title": title, "ghost": True})
            edges.append({"source": e["name"], "target": target})
    return {"nodes": nodes, "edges": edges, "vault": str(_dir(project_id))}
