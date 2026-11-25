"""Tests for scripts/board/reconcile-local-conflicts.py non-card expiry.

Card reconcile-local-conflicts-expire-stale-n-00974b: stale non-card
.local-conflict-* files (generated paths — upstream-authoritative) are
archived once they are older than RECONCILE_NONCARD_TTL_S; fresh files
keep flag-on-recent.

Card reconcile-noncard-conflicts-never-resolve: orphan non-card
conflicts (canonical deleted upstream — e.g. a focus-inbox entry moved
to processed/) quarantine on the longer RECONCILE_NONCARD_ORPHAN_TTL_S
instead of re-flagging forever, and a file whose flag already landed
inside the dedup window stays quiet on repeat runs.
"""
import importlib.util
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "board" / "reconcile-local-conflicts.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "reconcile_local_conflicts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def rlc():
    return _load()


def _tree(td: str):
    repo = Path(td)
    (repo / "docs/ssot/kanban/cards").mkdir(parents=True)
    (repo / "docs/ssot").mkdir(parents=True, exist_ok=True)
    return repo, repo / "docs/ssot"


def test_stale_noncard_expired_to_archive(rlc, tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", archive)
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "focus-inbox.yml").write_text("a: 1\n")
    stale = ssot / "focus-inbox.yml.local-conflict-20200101-000000"
    stale.write_text("a: 2\n")

    assert rlc.run(repo, dry=False) == 0
    assert not stale.exists()
    assert (ssot / "focus-inbox.yml").read_text() == "a: 1\n"
    archived = archive / stale.relative_to(repo)
    assert archived.read_text() == "a: 2\n"


def test_fresh_noncard_kept_and_flagged(rlc, tmp_path, monkeypatch):
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(rlc, "flag_via_api", lambda cid, text: True)
    monkeypatch.setattr(rlc, "FLAG_STATE", tmp_path / "flags.json")
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "x.yml").write_text("a: 1\n")
    ts = time.strftime("%Y%m%d-%H%M%S")
    fresh = ssot / f"x.yml.local-conflict-{ts}"
    fresh.write_text("a: 2\n")

    assert rlc.run(repo, dry=False) == 1
    assert fresh.exists()


def test_orphan_noncard_quarantined_after_ttl(rlc, tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", archive)
    monkeypatch.setattr(rlc, "flag_via_api", lambda cid, text: True)
    monkeypatch.setattr(rlc, "FLAG_STATE", tmp_path / "flags.json")
    repo, ssot = _tree(str(tmp_path / "repo"))
    ts = time.strftime("%Y%m%d-%H%M%S")
    recent = ssot / f"recent-gone.yml.local-conflict-{ts}"
    recent.write_text("a: 3\n")
    ancient = ssot / "ancient-gone.yml.local-conflict-20200101-000000"
    ancient.write_text("a: 4\n")

    # recent orphan: kept + flagged (leftover); ancient orphan:
    # archived out of the tree on the orphan TTL
    assert rlc.run(repo, dry=False) == 1
    assert recent.exists()
    assert not ancient.exists()
    assert (archive / ancient.relative_to(repo)).read_text() == "a: 4\n"


def test_already_flagged_noncard_is_quiet(rlc, tmp_path, monkeypatch,
                                        capsys):
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(rlc, "flag_via_api", lambda cid, text: True)
    monkeypatch.setattr(rlc, "FLAG_STATE", tmp_path / "flags.json")
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "x.yml").write_text("a: 1\n")
    ts = time.strftime("%Y%m%d-%H%M%S")
    fresh = ssot / f"x.yml.local-conflict-{ts}"
    fresh.write_text("a: 2\n")

    assert rlc.run(repo, dry=False) == 1
    assert "non-card conflict kept" in capsys.readouterr().err
    # second run inside the dedup window: no stderr, no leftover
    assert rlc.run(repo, dry=False) == 0
    assert capsys.readouterr().err == ""
    assert fresh.exists()


def test_dry_run_reports_but_keeps(rlc, tmp_path, monkeypatch):
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", tmp_path / "archive")
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "focus-inbox.yml").write_text("a: 1\n")
    stale = ssot / "focus-inbox.yml.local-conflict-20200101-000000"
    stale.write_text("a: 2\n")

    assert rlc.expire_noncard(stale, repo, dry=True) == "expired"
    assert stale.exists()


def test_expire_noncard_statuses(rlc, tmp_path, monkeypatch):
    monkeypatch.setattr(rlc, "NONCARD_TTL_S", 3600)
    monkeypatch.setattr(rlc, "NONCARD_ORPHAN_TTL_S", 7200)
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", tmp_path / "archive")
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "x.yml").write_text("a: 1\n")
    # orphan inside the orphan TTL -> kept as 'orphan'
    ts = time.strftime("%Y%m%d-%H%M%S")
    recent_orphan = ssot / f"gone.yml.local-conflict-{ts}"
    recent_orphan.write_text("a: 3\n")
    assert rlc.expire_noncard(
        recent_orphan, repo, dry=False) == "orphan"
    # orphan past the orphan TTL -> archived -> 'expired'
    old_orphan = ssot / "gone2.yml.local-conflict-20200101-000000"
    old_orphan.write_text("a: 4\n")
    assert rlc.expire_noncard(old_orphan, repo, dry=False) == "expired"
    assert not old_orphan.exists()
    fresh = ssot / "x.yml.local-conflict-29990101-000000"
    fresh.write_text("a: 2\n")
    # future timestamp -> age clamps to 0 -> fresh
    assert rlc.expire_noncard(fresh, repo, dry=False) == "fresh"
