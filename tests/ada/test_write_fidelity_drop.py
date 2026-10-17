"""Verification for the write-fidelity drop staged under
integrations/ada-voice/ (card ada-cms-write-fidelity / ADA-0732,
2026-10-17).

MEM-0498 (kk-cms-only bench 2026-10-12): Kaewta stored "Tuesdays" in
cms_publish_page content while narrating "Mondays" — the write
persisted. Root cause: the tool path is verbatim (content -> /add
contentMd untouched); the divergence is a model slip — narration and
tool args are separate generations.

The drop guards it three ways:
- tool-side read-back (cms.py): stored_verified + stored_excerpt echo
  into the publish result so the model can self-correct;
- provider-side write_fidelity ops event (realtime_provider.py):
  fact-token contradiction between narration/user-seed and the
  persisted content arg;
- bench-side deterministic assertion: kk_cms_only_seeded_recall's
  confirm turn asserts call_args_contain for the seeded facts.

Logic coverage lives ada-voice-side in tests/test_write_fidelity.py
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
PATCH = DROP / "backend" / "write-fidelity.patch"
TEST_FILE = DROP / "tests" / "test_write_fidelity.py"
README = DROP / "README.md"
JOB = REPO / "docs" / "ssot" / "jobs" / "ada" / "2026-10-17-cms-write-fidelity.yml"

ADA_PI = Path.home() / "CascadeProjects" / "ada-voice"


@pytest.fixture(scope="module")
def patch_text():
    return PATCH.read_text()


def test_patch_covers_all_three_files(patch_text):
    for path in ("backend/tool_runner/cms.py",
                 "backend/realtime_provider.py",
                 "tests/scenarios-live/kk_cms_only_seeded_recall.yaml"):
        assert f"a/{path}" in patch_text, f"patch missing {path}"


def test_patch_carries_the_three_guards(patch_text):
    # tool-side read-back
    for marker in ("stored_verified", "stored_sha256", "stored_excerpt",
                   "get_document(CMS_COLLECTION, slug, lang)"):
        assert marker in patch_text, f"read-back marker {marker!r} missing"
    # provider-side ops check
    for marker in ("_write_fidelity_problems", "turn_fidelity_calls",
                   '"write_fidelity"', "_FIDELITY_WRITE_TOOLS"):
        assert marker in patch_text, f"provider marker {marker!r} missing"
    # bench-side assertion
    for marker in ("call_args_contain", "calls_any: [cms_publish_page]"):
        assert marker in patch_text, f"scenario marker {marker!r} missing"


def test_unit_test_file_staged_and_compiles():
    assert TEST_FILE.exists()
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", str(TEST_FILE)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    for marker in ("_write_fidelity_problems", "stored_verified",
                   "test_stored_tuesday_vs_narrated_monday_flags"):
        assert marker in TEST_FILE.read_text()


def test_readme_lists_the_drop():
    text = README.read_text()
    assert "Drop 13" in text and "write-fidelity.patch" in text


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
        f"write-fidelity.patch {state} vs ada-voice checkout"
