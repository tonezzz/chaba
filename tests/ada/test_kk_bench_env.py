"""Unit tests for the kk-bench-env.py safety helpers.

No SSH, no live hosts — only pure env-text helpers and the dev-lane guard.
The live apply path (backup -> write -> read-back -> restart -> health,
with rollback) is exercised by the script itself; these tests pin the
parts that can be checked offline (MEM-0498 / re-test step 3).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/kk-bench-env.py"

_spec = importlib.util.spec_from_file_location("kk_bench_env", SCRIPT)
kk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kk)

PROF = {
    "instance": "kk-dev",
    "env_file": "ada-kk-dev.env",
    "host": "idc03",
    "port": 8009,
    "include": ["cms_read", "cms_publish_page"],
    "exclude": ["ada_memory_search", "web_search"],
}
BLOCK = kk.render_block("kk-cms-only", PROF)


def test_render_block_shape() -> None:
    assert BLOCK.startswith(kk.BLOCK_BEGIN + " (bench_profiles.kk-cms-only")
    assert BLOCK.rstrip().endswith(kk.BLOCK_END)
    assert "ADA_INCLUDED_TOOLS=cms_read,cms_publish_page\n" in BLOCK
    assert "ADA_EXCLUDED_TOOLS=ada_memory_search,web_search\n" in BLOCK


def test_merge_block_replaces_managed_block() -> None:
    old = "KEEP=1\n" + BLOCK + "TAIL=1\n"
    new_block = kk.render_block("kk-parity", PROF)
    merged = kk.merge_block(old, new_block)
    assert "KEEP=1" in merged and "TAIL=1" in merged
    assert BLOCK not in merged
    assert merged.count(kk.BLOCK_BEGIN) == 1
    assert "bench_profiles.kk-parity" in merged


def test_merge_block_comments_hand_written_managed_vars() -> None:
    text = ("ADA_INCLUDED_TOOLS=smuggled\n"
            "OTHER=keep-me\n")
    merged = kk.merge_block(text, BLOCK)
    assert "# migrated to managed block below: ADA_INCLUDED_TOOLS=smuggled" in merged
    assert "OTHER=keep-me" in merged
    assert kk.extract_block(merged) == BLOCK


def test_extract_block_missing_returns_empty() -> None:
    assert kk.extract_block("ADA_INCLUDED_TOOLS=x\n") == ""
    assert kk.extract_block("") == ""


def test_block_status_and_changes() -> None:
    current = "KEEP=1\n" + kk.render_block("kk-parity", PROF)
    assert kk.block_status(current, BLOCK) is False
    assert kk.block_status("KEEP=1\n" + BLOCK, BLOCK) is True

    change = kk.describe_changes(kk.extract_block(current), BLOCK)
    assert "bench_profiles.kk-parity @ ssot.apps.ada-persons.yml" in change
    assert "bench_profiles.kk-cms-only @ ssot.apps.ada-persons.yml" in change
    # same tool lists in this fixture → only the label differs
    assert "included +:" not in change

    different = kk.render_block("kk-cms-only", {**PROF,
                               "include": ["cms_read"],
                               "exclude": ["web_search"]})
    change = kk.describe_changes(BLOCK, different)
    assert "included -: cms_publish_page" in change
    assert "excluded -: ada_memory_search" in change
    assert "unchanged" == kk.describe_changes(BLOCK, BLOCK)


def test_env_knobs_block_round_trip() -> None:
    prof = {**PROF, "env_knobs": {"ADA_SESSION_PRIME": "0"}}
    knob_block = kk.render_knobs_block("kk-cms-only", prof)
    assert "ADA_SESSION_PRIME=0" in knob_block
    wanted = kk.desired_text(kk.render_block("kk-cms-only", PROF), knob_block)
    base = "ADA_OTHER=keep\nADA_SESSION_PRIME=1\n"
    merged = kk.merge_knobs_block(kk.merge_block(base,
                                                 kk.render_block("kk-cms-only", PROF)),
                                  knob_block)
    assert "ADA_OTHER=keep" in merged
    assert "# migrated to managed block below: ADA_SESSION_PRIME=1" in merged
    assert kk.block_status(merged, wanted) is True
    assert "env knobs: ADA_SESSION_PRIME=0" in kk.describe_changes(
        kk.managed_text(base), wanted)


def test_dev_lane_guard() -> None:
    kk.assert_dev_profile("kk-cms-only", PROF)  # no raise
    with pytest.raises(SystemExit, match="-dev env"):
        kk.assert_dev_profile("bad", {**PROF, "env_file": "ada-kk.env"})
    with pytest.raises(SystemExit, match="kk-dev"):
        kk.assert_dev_profile("bad", {**PROF, "instance": "kk"})
