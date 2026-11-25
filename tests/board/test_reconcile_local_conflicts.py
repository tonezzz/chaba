"""Tests for scripts/board/reconcile-local-conflicts.py non-card expiry.

Card reconcile-local-conflicts-expire-stale-n-00974b: stale non-card
.local-conflict-* files (generated paths — upstream-authoritative) are
archived once their canonical base exists and they are older than
RECONCILE_NONCARD_TTL_S; fresh and orphan files keep flag-on-recent.
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


def test_orphan_noncard_never_expires(rlc, tmp_path, monkeypatch):
    monkeypatch.setattr(rlc, "ARCHIVE_ROOT", tmp_path / "archive")
    monkeypatch.setattr(rlc, "flag_via_api", lambda cid, text: True)
    monkeypatch.setattr(rlc, "FLAG_STATE", tmp_path / "flags.json")
    repo, ssot = _tree(str(tmp_path / "repo"))
    orphan = ssot / "gone.yml.local-conflict-20200101-000000"
    orphan.write_text("a: 3\n")

    assert rlc.run(repo, dry=False) == 1
    assert orphan.exists()


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
    repo, ssot = _tree(str(tmp_path / "repo"))
    (ssot / "x.yml").write_text("a: 1\n")
    assert rlc.expire_noncard(
        ssot / "missing.yml.local-conflict-20200101-000000",
        repo, dry=False) == "orphan"
    fresh = ssot / "x.yml.local-conflict-29990101-000000"
    fresh.write_text("a: 2\n")
    # future timestamp -> age clamps to 0 -> fresh
    assert rlc.expire_noncard(fresh, repo, dry=False) == "fresh"
