"""File versioning — git for people who've never heard of git.

Every change the agent makes (and any outside edit it encounters) is saved as
a Version: who, when, and *which ask caused it*. Content lives in a
content-addressed blob store; metadata in SQLite. Friendly verbs only:
versions, what changed, restore.
"""
import difflib
import hashlib
from pathlib import Path

from .config import CONFIG_DIR

MAX_BLOB = 2_000_000  # don't version >2MB files


def _blob_dir(project_id: str) -> Path:
    return CONFIG_DIR / "versions" / project_id


def _blob_path(project_id: str, hash_: str) -> Path:
    return _blob_dir(project_id) / hash_[:2] / hash_


class VersionStore:
    def __init__(self, store):
        self.store = store

    def _write_blob(self, project_id: str, data: bytes) -> str:
        h = hashlib.sha256(data).hexdigest()
        p = _blob_path(project_id, h)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return h

    def read_blob(self, project_id: str, hash_: str) -> bytes | None:
        p = _blob_path(project_id, hash_)
        return p.read_bytes() if p.exists() else None

    def snapshot(self, project_id: str, path: Path, rel: str, author_kind: str,
                 author_id: str, run_id: str = "", label: str = "") -> str | None:
        """Record the file's current content as a version. Skips if identical
        to the latest recorded version. Returns version id or None."""
        if not path.is_file() or path.stat().st_size > MAX_BLOB:
            return None
        data = path.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        latest = self.store.latest_version(project_id, rel)
        if latest and latest["hash"] == h:
            return None
        self._write_blob(project_id, data)
        return self.store.add_file_version(
            project_id, rel, h, len(data), author_kind, author_id, run_id, label)

    def capture_external(self, project_id: str, path: Path, rel: str) -> str | None:
        """If the file on disk differs from the last tracked version, record
        the outside edit first so nobody's work is ever lost."""
        latest = self.store.latest_version(project_id, rel)
        if not latest:
            return None
        return self.snapshot(project_id, path, rel, "external", "",
                             label="edited outside Poseidon")

    def diff(self, project_id: str, version: dict) -> dict:
        """What changed in this version vs the one before it."""
        cur = self.read_blob(project_id, version["hash"]) or b""
        prev_v = self.store.prev_version(version)
        prev = self.read_blob(project_id, prev_v["hash"]) if prev_v else b""
        if b"\x00" in cur[:4096] or (prev and b"\x00" in prev[:4096]):
            return {"binary": True, "lines": []}
        cur_l = cur.decode(errors="replace").splitlines()
        prev_l = (prev or b"").decode(errors="replace").splitlines()
        lines = []
        for ln in difflib.unified_diff(prev_l, cur_l, lineterm="", n=2):
            if ln.startswith("---") or ln.startswith("+++"):
                continue
            t = "add" if ln.startswith("+") else "del" if ln.startswith("-") else "ctx" if not ln.startswith("@@") else "hunk"
            lines.append({"t": t, "s": ln[:300]})
            if len(lines) >= 400:
                lines.append({"t": "hunk", "s": "… (truncated)"})
                break
        return {"binary": False, "lines": lines, "first": prev_v is None}

    def restore(self, project_id: str, workdir: Path, version: dict,
                member_id: str) -> dict:
        data = self.read_blob(project_id, version["hash"])
        if data is None:
            return {"error": "version content missing"}
        target = (workdir / version["path"]).resolve()
        if not target.is_relative_to(workdir):
            return {"error": "path escapes project"}
        # capture whatever is there now first — restores never destroy
        self.capture_external(project_id, target, version["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.snapshot(project_id, target, version["path"], "member", member_id,
                      label=f"restored version from {version['id']}")
        return {"ok": True, "path": version["path"]}
