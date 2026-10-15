"""Verification for the correction-command drop staged under
integrations/ada-voice/ (card correction-commands-die-at-the-confirm-gate,
OPS-0567, transcript 2026-10-13-cac2984711 — 'CRV เป็นรถของกุ้ง
ไม่ใช่ของผมนะ แก้ไขด้วย' died at the confirm gate).

Applies the two staged patches to a COPY of the ada-voice checkout
(ADA_PI env or ~/CascadeProjects/ada-voice), drops in the new
test_memory_directive unit file, and runs it with the checkout's venv —
the tests pin the directive detector (explicit store/correct/retract
orders authorize the memory-write seats; negated/questioning/recollection
forms do not) and the seat scoping (actuation/publish tools never
directed). Skips when no checkout/venv is reachable (the patches are
what ship, not the tree).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
PATCHES = [
    "backend/realtime_provider.correction-command.patch",
    "backend/tool_guide.correction-command.patch",
]
TESTFILE = DROP / "tests" / "test_memory_directive.py"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects" / "ada-voice")))


def _scratch_tree(tmp_path: Path) -> Path:
    """Copy the ada-voice checkout and apply the staged patches."""
    dst = tmp_path / "ada-voice"
    subprocess.run(
        ["git", "clone", "-q", str(ADA_PI), str(dst)],
        check=True, timeout=120)
    for rel in PATCHES:
        subprocess.run(
            ["git", "apply", str(DROP / rel)],
            cwd=dst, check=True, timeout=30)
    shutil.copy(TESTFILE, dst / "tests" / "test_memory_directive.py")
    return dst


@pytest.mark.skipif(not (ADA_PI / ".git").exists()
                    or not (ADA_PI / ".venv" / "bin" / "python").exists(),
                    reason="no ada-voice checkout/venv reachable")
def test_patches_apply_and_directive_tests_pass(tmp_path):
    tree = _scratch_tree(tmp_path)
    # The clone ships no venv — the source checkout's interpreter picks
    # up the cloned tree's backend/ via cwd on sys.path.
    proc = subprocess.run(
        [str(ADA_PI / ".venv" / "bin" / "python"), "-m", "pytest",
         "tests/test_memory_directive.py", "-x", "-q"],
        cwd=tree, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, (
        proc.stdout[-2000:] + proc.stderr[-2000:])


@pytest.mark.skipif(not (ADA_PI / ".git").exists(),
                    reason="no ada-voice checkout reachable")
def test_patches_apply_clean(tmp_path):
    """git apply --check alone — the base-commit guard."""
    dst = tmp_path / "ada-voice"
    subprocess.run(["git", "clone", "-q", str(ADA_PI), str(dst)],
                   check=True, timeout=120)
    for rel in PATCHES:
        proc = subprocess.run(["git", "apply", "--check", str(DROP / rel)],
                              cwd=dst, capture_output=True, text=True)
        assert proc.returncode == 0, f"{rel}: {proc.stderr[-500:]}"
