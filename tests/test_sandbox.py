"""Sandbox mode (v0.10): clone → change → status → diff → promote/discard.

Also the repo's first tests — run with `pytest` from the repo root.
CONFIG_DIR is monkeypatched so nothing touches the real ~/.poseidon.
"""

import json
from pathlib import Path

import pytest

from poseidon import sandbox


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fake project folder + an isolated CONFIG_DIR."""
    cfg = tmp_path / "poseidon-home"
    monkeypatch.setattr(sandbox, "CONFIG_DIR", cfg)
    work = tmp_path / "project"
    work.mkdir()
    (work / "keep.txt").write_text("unchanged\n")
    (work / "notes.md").write_text("original notes\n")
    (work / "sub").mkdir()
    (work / "sub" / "data.txt").write_text("v1\n")
    return work


class FakeVersions:
    """Records version-store calls so promote's contract is checkable."""

    def __init__(self):
        self.captured = []
        self.snapshots = []

    def capture_external(self, project_id, path, rel):
        self.captured.append(rel)

    def snapshot(self, project_id, path, rel, author_kind, author_id,
                 run_id="", label=""):
        self.snapshots.append((rel, label))


def test_clone_creates_manifest(env):
    sb = sandbox.clone("proj", env, "session1234")
    assert (sb / "keep.txt").read_text() == "unchanged\n"
    manifest = json.loads((sb / sandbox.MANIFEST).read_text())
    assert "keep.txt" in manifest and "sub/data.txt" in manifest


def test_status_classifies_changes(env):
    sb = sandbox.clone("proj", env, "session1234")
    (sb / "notes.md").write_text("edited in sandbox\n")
    (sb / "new.txt").write_text("brand new\n")
    (sb / "sub" / "data.txt").unlink()

    st = sandbox.status(env, sb)
    assert st["added"] == ["new.txt"]
    assert st["changed"] == ["notes.md"]
    assert st["deleted"] == ["sub/data.txt"]
    assert st["conflicts"] == []
    assert not st["clean"]


def test_conflict_when_origin_moves(env):
    sb = sandbox.clone("proj", env, "session1234")
    (sb / "notes.md").write_text("sandbox edit\n")
    (env / "notes.md").write_text("origin also edited\n")

    st = sandbox.status(env, sb)
    assert "notes.md" in st["conflicts"]


def test_diff_file_shows_change(env):
    sb = sandbox.clone("proj", env, "session1234")
    (sb / "notes.md").write_text("original notes\nplus a new line\n")
    d = sandbox.diff_file(env, sb, "notes.md")
    assert not d["binary"]
    assert any(l["t"] == "add" and "new line" in l["s"] for l in d["lines"])


def test_promote_applies_through_versions(env):
    sb = sandbox.clone("proj", env, "session1234")
    (sb / "notes.md").write_text("edited in sandbox\n")
    (sb / "new.txt").write_text("brand new\n")
    (sb / "sub" / "data.txt").unlink()

    fv = FakeVersions()
    result = sandbox.promote("proj", env, sb, fv, "owner")

    assert (env / "notes.md").read_text() == "edited in sandbox\n"
    assert (env / "new.txt").read_text() == "brand new\n"
    assert not (env / "sub" / "data.txt").exists()
    assert sorted(result["promoted"]) == ["new.txt", "notes.md"]
    assert result["removed"] == ["sub/data.txt"]
    # every touched real file went through the version store
    assert "notes.md" in fv.captured and "sub/data.txt" in fv.captured
    assert any(rel == "notes.md" for rel, _ in fv.snapshots)


def test_promote_selected_files_only(env):
    sb = sandbox.clone("proj", env, "session1234")
    (sb / "notes.md").write_text("edited\n")
    (sb / "new.txt").write_text("new\n")

    sandbox.promote("proj", env, sb, FakeVersions(), "owner", files=["new.txt"])
    assert (env / "new.txt").exists()
    assert (env / "notes.md").read_text() == "original notes\n"  # untouched


def test_discard_refuses_paths_outside_root(env, tmp_path):
    sb = sandbox.clone("proj", env, "session1234")
    outside = tmp_path / "innocent"
    outside.mkdir()
    assert sandbox.discard(outside) is False
    assert outside.exists()
    assert sandbox.discard(sb) is True
    assert not sb.exists()


def test_identical_rewrite_is_not_a_change(env):
    sb = sandbox.clone("proj", env, "session1234")
    # rewrite with identical content — mtime moves, content doesn't
    (sb / "keep.txt").write_text("unchanged\n")
    st = sandbox.status(env, sb)
    assert st["changed"] == []
    assert st["clean"]
