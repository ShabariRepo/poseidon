"""Sandbox mode: branches for non-developers.

Completes the "git for non-devs" story: file versions are the commits,
a sandbox is the branch, promote is the merge, and the working-tree view
is `git status` — without anyone ever seeing git.

A sandbox is a clone of the project folder under ~/.poseidon/sandboxes/.
Cloning uses copy-on-write when the OS supports it (instant + near-zero
disk on APFS/btrfs/xfs), plain copy otherwise. While a session's sandbox
is active, the tool jail points at the clone, so every file write, edit
and command runs against the copy. Promote applies the changes back to
the real folder THROUGH the version store (so even the merge is versioned
and reversible); discard just deletes the clone.

A manifest of (size, mtime) signatures is written at clone time so the
working tree can distinguish "changed in the sandbox" from "changed in
the real folder underneath" (a conflict).
"""

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from .config import CONFIG_DIR

MANIFEST = ".poseidon-sandbox.json"
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".poseidon", ".idea", ".vscode"}
IGNORE_FILES = {".DS_Store", MANIFEST}
MAX_HASH_SIZE = 5_000_000
MAX_DIFF_LINES = 400


def sandbox_root() -> Path:
    return CONFIG_DIR / "sandboxes"


def _walk(root: Path):
    """Yield (relpath, [size, mtime_ns]) for every tracked file under root."""
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for c in children:
            if c.is_symlink():
                continue
            if c.is_dir():
                if c.name not in IGNORE_DIRS:
                    stack.append(c)
            elif c.is_file() and c.name not in IGNORE_FILES:
                st = c.stat()
                yield str(c.relative_to(root)), [st.st_size, st.st_mtime_ns]


def _hash(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_HASH_SIZE:
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _same_content(a: Path, b: Path) -> bool:
    ha, hb = _hash(a), _hash(b)
    return ha is not None and ha == hb


def clone(project_id: str, workdir: Path, session_id: str) -> Path:
    dest = sandbox_root() / f"{project_id}-{session_id[:8]}-{int(time.time())}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Copy-on-write clone where the filesystem supports it; both cp variants
    # fall back to a regular copy on their own, shutil is the last resort.
    try:
        subprocess.run(["cp", "-Rc", str(workdir), str(dest)],
                       check=True, capture_output=True)  # macOS clonefile
    except Exception:
        try:
            subprocess.run(["cp", "-R", "--reflink=auto", str(workdir), str(dest)],
                           check=True, capture_output=True)  # linux reflink
        except Exception:
            shutil.copytree(workdir, dest, symlinks=False,
                            ignore=shutil.ignore_patterns(*IGNORE_DIRS))
    manifest = dict(_walk(workdir))
    (dest / MANIFEST).write_text(json.dumps(manifest))
    return dest


def load_manifest(sandbox: Path) -> dict:
    try:
        return json.loads((sandbox / MANIFEST).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def status(workdir: Path, sandbox: Path) -> dict:
    """The working tree: what the sandbox changed vs the clone-time baseline,
    plus conflicts where the real folder moved underneath."""
    baseline = load_manifest(sandbox)
    sb = dict(_walk(sandbox))
    og = dict(_walk(workdir))

    added, changed, deleted, conflicts = [], [], [], []
    for rel, sig in sb.items():
        base = baseline.get(rel)
        if base is None:
            added.append(rel)
            if rel in og and not _same_content(sandbox / rel, workdir / rel):
                conflicts.append(rel)
        elif sig != base:
            # signature moved — confirm it isn't a content-identical rewrite
            if rel in og and og.get(rel) == base and _same_content(sandbox / rel, workdir / rel):
                continue
            changed.append(rel)
            if rel in og and og.get(rel) != base:
                conflicts.append(rel)
    for rel, base in baseline.items():
        if rel not in sb:
            deleted.append(rel)
            if rel in og and og.get(rel) != base:
                conflicts.append(rel)

    return {
        "added": sorted(added),
        "changed": sorted(changed),
        "deleted": sorted(deleted),
        "conflicts": sorted(set(conflicts)),
        "clean": not (added or changed or deleted),
    }


def diff_file(workdir: Path, sandbox: Path, rel: str) -> dict:
    """Real folder vs sandbox for one file — same {binary, lines} shape as
    VersionStore.diff so the UI renders both with one code path."""
    import difflib

    def read(p: Path):
        try:
            return p.read_bytes() if p.is_file() else b""
        except OSError:
            return b""

    old, new = read(workdir / rel), read(sandbox / rel)
    if b"\x00" in old[:4096] or b"\x00" in new[:4096]:
        return {"binary": True, "lines": []}
    lines = []
    for ln in difflib.unified_diff(
        old.decode(errors="replace").splitlines(),
        new.decode(errors="replace").splitlines(),
        lineterm="", n=2,
    ):
        if ln.startswith("---") or ln.startswith("+++"):
            continue
        t = ("add" if ln.startswith("+") else "del" if ln.startswith("-")
             else "ctx" if not ln.startswith("@@") else "hunk")
        lines.append({"t": t, "s": ln[:300]})
        if len(lines) >= MAX_DIFF_LINES:
            lines.append({"t": "hunk", "s": "… (truncated)"})
            break
    return {"binary": False, "lines": lines}


def promote(project_id: str, workdir: Path, sandbox: Path, versions,
            member_id: str, files: list | None = None) -> dict:
    """Apply sandbox changes to the real folder through the version store —
    every overwritten/deleted file is captured first and every promoted file
    is snapshotted, so the merge itself is reversible file by file."""
    st = status(workdir, sandbox)
    wanted = set(files) if files else None
    pick = lambda rels: [r for r in rels if wanted is None or r in wanted]

    promoted, removed = [], []
    for rel in pick(st["added"]) + pick(st["changed"]):
        src, dst = sandbox / rel, workdir / rel
        if not src.is_file():
            continue
        versions.capture_external(project_id, dst, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        versions.snapshot(project_id, dst, rel, "member", member_id,
                          label="promoted from sandbox")
        promoted.append(rel)
    for rel in pick(st["deleted"]):
        dst = workdir / rel
        if dst.is_file():
            # preserve the content before it goes — deletions must be undoable
            versions.capture_external(project_id, dst, rel)
            versions.snapshot(project_id, dst, rel, "member", member_id,
                              label="deleted via sandbox promote (content preserved)")
            dst.unlink()
        removed.append(rel)

    return {"ok": True, "promoted": promoted, "removed": removed,
            "conflicts": st["conflicts"]}


def discard(sandbox: Path) -> bool:
    """Delete a sandbox folder. Refuses anything outside the sandbox root."""
    sandbox = sandbox.resolve()
    if not sandbox.is_relative_to(sandbox_root().resolve()) or not sandbox.is_dir():
        return False
    shutil.rmtree(sandbox, ignore_errors=True)
    return True
