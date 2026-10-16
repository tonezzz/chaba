"""Verification for the cast-wrong-target / failure-loop drop staged
under integrations/ada-voice/ (card ada-cast-wrong-target-verbose-loop,
ADA-0684, Tony voice session 2026-10-14 4029a6447f).

Applies the six staged patches to a COPY of the ada-voice checkout
(ADA_PI env or ~/CascadeProjects/ada-voice), drops in the new
cast_wrong_target_loop scenario, and runs ada-voice's own offline
scenario engine against it via the checkout's .venv — the scenario
replays the incident shape end to end: wrong-target cast, unavailable
entity, cross-tool stop_and_ask, corrected tv_action retry, storm
floor. Skips when no checkout/venv is reachable (the patches are what
ship, not the tree).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.ada._drops import apply_patch, check_patch, drop_guard_ok

REPO = Path(__file__).resolve().parents[2]
DROP = REPO / "integrations" / "ada-voice"
PATCHES = [
    "backend/screens.delivered-zero.patch",
    "backend/ha.unavailable-precheck.patch",
    "backend/tool_runner.goal-loop.patch",
    "backend/common.goal-loop.patch",
    "backend/tool_guide.target-fidelity.patch",
    "backend/realtime_provider.cast-loop.patch",
]
SCENARIO = DROP / "tests" / "scenarios" / "cast_wrong_target_loop.yaml"
ADA_PI = Path(os.environ.get(
    "ADA_PI", str(Path.home() / "CascadeProjects" / "ada-voice")))


def _scratch_tree(tmp_path: Path) -> Path:
    """Copy the ada-voice checkout and apply every staged patch."""
    dst = tmp_path / "ada-voice"
    # file:// + depth 1: a plain local-path clone packs the full object
    # store (~86M, minutes on the HDD); the scenario only needs HEAD.
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1",
         ADA_PI.as_uri(), str(dst)],
        check=True, timeout=120)
    for rel in PATCHES:
        apply_patch(DROP / rel, dst)
    shutil.copy(SCENARIO, dst / "tests" / "scenarios" /
                "cast_wrong_target_loop.yaml")
    return dst


@pytest.mark.skipif(not (ADA_PI / ".git").exists()
                    or not (ADA_PI / ".venv" / "bin" / "python").exists(),
                    reason="no ada-voice checkout/venv reachable")
def test_patches_apply_and_scenario_passes(tmp_path):
    tree = _scratch_tree(tmp_path)
    # The clone ships no venv — the source checkout's interpreter picks
    # up the cloned tree's backend/ via cwd on sys.path.
    proc = subprocess.run(
        [str(ADA_PI / ".venv" / "bin" / "python"), "-c",
         "import asyncio, json, sys; sys.path.insert(0, 'tests');"
         " from scenario_engine import run_scenario;"
         " r = asyncio.run(run_scenario("
         " 'tests/scenarios/cast_wrong_target_loop.yaml'));"
         " print(json.dumps({'ok': r['ok'], 'failures': r['failures']}))"],
        cwd=tree, capture_output=True, text=True, timeout=300)
    # The engine prints runner logs before the JSON — the report is the
    # last line.
    report = None
    for line in reversed(proc.stdout.strip().splitlines()):
        if line.startswith("{"):
            import json
            report = json.loads(line)
            break
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert report is not None, proc.stdout[-2000:]
    assert report["ok"], report["failures"]


@pytest.mark.skipif(not (ADA_PI / ".git").exists(),
                    reason="no ada-voice checkout reachable")
def test_patches_apply_clean(tmp_path):
    """Base-commit guard: every patch must apply OR already be merged
    upstream; divergence only fails when nothing in the drop landed
    (pending drop on a rotted base — tests/ada/_drops.py)."""
    dst = tmp_path / "ada-voice"
    subprocess.run(["git", "clone", "-q", "--depth", "1",
                    ADA_PI.as_uri(), str(dst)],
                   check=True, timeout=120)
    states = {rel: check_patch(DROP / rel, dst) for rel in PATCHES}
    assert drop_guard_ok(states.values()), (
        f"drop rotted on its base — re-dispatch: {states}")
