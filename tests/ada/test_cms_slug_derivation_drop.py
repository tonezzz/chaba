"""Verification for the cms_publish_page slug-derivation drop staged
under integrations/ada-voice/ (card fix-cms-publish-page-slug-argument-
missi-96152a / KNB-0624, 2026-10-27).

Session audit signature fail:cms_publish_page: the model calls with
title+content and no slug, the lazy-schema gate answers SchemaError
'missing required slug', and the publish dies before the confirm
handshake. The drop makes slug= optional — _cms_slugify derives the id
from the title — and keys the pending-confirm slot by the same
derivation so register/confirm stay matched.

Logic coverage lives ada-voice-side in tests/test_cms_slug_derivation.py
(staged copy here) — this suite guards the staged artifacts and the
patch's applyability to the checkout (merged/diverged via _drops).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.ada._drops import check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
PATCH = DROP / "backend" / "cms-slug-derivation.patch"
TEST_FILE = DROP / "tests" / "test_cms_slug_derivation.py"
README = DROP / "README.md"
JOB = REPO / "docs" / "ssot" / "jobs" / "ada" / \
    "2026-10-27-cms-publish-slug-derivation.yml"

ADA_PI = Path.home() / "CascadeProjects" / "ada-voice"


@pytest.fixture(scope="module")
def patch_text():
    return PATCH.read_text()


def test_patch_covers_all_five_files(patch_text):
    for path in ("backend/tool_runner/cms.py",
                 "backend/tool_runner/__init__.py",
                 "backend/realtime_provider.py",
                 "backend/tool_guide.yml",
                 "tests/test_cms_slug_derivation.py"):
        assert f"a/{path}" in patch_text, f"patch missing {path}"


def test_patch_carries_the_derivation(patch_text):
    # tool-side helper + optional slug
    for marker in ("_cms_slugify", 'slug: str = ""',
                   "slug missing and none derivable from title"):
        assert marker in patch_text, f"tool marker {marker!r} missing"
    # pending-key uses the same derivation
    assert 'self._cms_slugify(str(args.get("title") or ""))' in patch_text
    # schema-side: slug leaves required (the removal diff-line is proof)
    assert '"required": ["slug", "title", "content"' in patch_text
    assert '"required": ["title", "content", "summary",' in patch_text


def test_unit_test_file_staged_and_compiles():
    assert TEST_FILE.exists()
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(TEST_FILE)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    for marker in ("_cms_slugify", "test_no_slug_derives_from_title",
                   "test_explicit_slug_still_wins"):
        assert marker in TEST_FILE.read_text()


def test_readme_lists_the_drop():
    text = README.read_text()
    assert "Drop 16" in text and "cms-slug-derivation.patch" in text


def test_job_record_exists():
    assert JOB.exists()


@pytest.mark.skipif(not (ADA_PI / ".git").exists(),
                    reason="no ada-voice checkout reachable")
def test_patch_state_vs_checkout(tmp_path):
    dst = tmp_path / "ada-voice"
    subprocess.run(["git", "clone", "-q", str(ADA_PI), str(dst)],
                   check=True, timeout=120)
    state = check_patch(PATCH, dst)
    assert drop_guard_ok([state]), \
        f"cms-slug-derivation.patch {state} vs ada-voice checkout"
