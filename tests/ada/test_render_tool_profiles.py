"""Unit tests for render-tool-profiles.py env_knobs support.

persons.<key>.tools.env_knobs renders a second managed block
(ada-env-knobs) into the prod env file — added for the kk CMS-only
memory pilot (card kk-cms-only-memory-pilot-acceptance, 2026-11-26) so
ADA_SESSION_PRIME / ADA_PRIME_SKIP_HISTORY are declared in SSOT instead
of hand-edited on idc03. No SSH, no live hosts — pure text helpers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts/ada/render-tool-profiles.py"

_spec = importlib.util.spec_from_file_location("render_tool_profiles", SCRIPT)
rtp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rtp)

PROF = {
    "instance": "kk",
    "env_file": "kk-ha/backend.env",
    "host": "idc03",
    "include": ["cms_read"],
    "exclude": ["ada_memory_search"],
    "env_knobs": {"ADA_SESSION_PRIME": "1", "ADA_PRIME_SKIP_HISTORY": "1"},
}
TOOL_BLOCK = rtp.render_block("kk", PROF)
KNOB_BLOCK = rtp.render_knobs_block("kk", PROF)


def test_load_profiles_carries_env_knobs() -> None:
    profiles = rtp.load_profiles()
    kk = profiles["kk"]
    assert kk["env_knobs"] == {
        "ADA_SESSION_PRIME": "1",
        "ADA_PRIME_SKIP_HISTORY": "1",
    }
    # persons without env_knobs stay unmanaged (None, not {}).
    assert profiles["tony"]["env_knobs"] is None


def test_render_knobs_block_shape() -> None:
    assert KNOB_BLOCK.startswith(rtp.KNOB_BEGIN + " (persons.kk @")
    assert KNOB_BLOCK.rstrip().endswith(rtp.KNOB_END)
    # sorted keys, one KEY=value per line
    assert "ADA_PRIME_SKIP_HISTORY=1\n" in KNOB_BLOCK
    assert "ADA_SESSION_PRIME=1\n" in KNOB_BLOCK
    assert KNOB_BLOCK.index("ADA_PRIME_SKIP_HISTORY") < \
        KNOB_BLOCK.index("ADA_SESSION_PRIME")


def test_render_knobs_block_none_is_empty() -> None:
    prof = {**PROF, "env_knobs": None}
    assert rtp.render_knobs_block("tony", prof) == ""


def test_render_knobs_block_empty_map_clears() -> None:
    prof = {**PROF, "env_knobs": {}}
    block = rtp.render_knobs_block("kk", prof)
    assert block.startswith(rtp.KNOB_BEGIN)
    assert block.rstrip().endswith(rtp.KNOB_END)
    assert "ADA_" not in block


def test_merge_appends_knob_block_and_retires_handwritten() -> None:
    current = (
        "ADA_CMS_CATALOG_PRIME=1\n"
        "ADA_PRIME_SKIP_HISTORY=0\n"          # hand-written stale knob
        + TOOL_BLOCK.replace(
            "ADA_INCLUDED_TOOLS=cms_read",
            "ADA_INCLUDED_TOOLS=ada_memory_search,cms_read") +
        "OTHER=keep\n"
    )
    merged = rtp.merge_env(current, TOOL_BLOCK, KNOB_BLOCK)
    assert merged.count(rtp.BLOCK_BEGIN) == 1
    assert merged.count(rtp.KNOB_BEGIN) == 1
    assert "# migrated to managed block below: ADA_PRIME_SKIP_HISTORY=0" \
        in merged
    assert "ADA_CMS_CATALOG_PRIME=1" in merged
    assert "OTHER=keep" in merged
    # live knob values come only from the managed block
    assert merged.count("ADA_PRIME_SKIP_HISTORY=1") == 1
    assert merged.count("ADA_SESSION_PRIME=1") == 1


def test_merge_replaces_existing_knob_block() -> None:
    stale = (
        rtp.KNOB_BEGIN + " (persons.kk @ old)\n"
        "ADA_PRIME_SKIP_HISTORY=0\n"
        "ADA_SESSION_PRIME=0\n"
        + rtp.KNOB_END + "\n"
    )
    merged = rtp.merge_env("KEEP=1\n" + stale, TOOL_BLOCK, KNOB_BLOCK)
    assert merged.count(rtp.KNOB_BEGIN) == 1
    assert "ADA_PRIME_SKIP_HISTORY=0" not in merged
    assert "ADA_SESSION_PRIME=0" not in merged


def test_merge_idempotent() -> None:
    current = "A=1\n" + TOOL_BLOCK + KNOB_BLOCK + "B=2\n"
    once = rtp.merge_env(current, TOOL_BLOCK, KNOB_BLOCK)
    assert rtp.merge_env(once, TOOL_BLOCK, KNOB_BLOCK) == once


def test_merge_without_knobs_leaves_file_alone() -> None:
    current = "A=1\n" + TOOL_BLOCK + "B=2\n"
    merged = rtp.merge_env(current, TOOL_BLOCK, "")
    assert rtp.KNOB_BEGIN not in merged
    assert merged == current


def test_kk_profile_pilot_surface() -> None:
    """The declared prod pilot: five drops out of include, into exclude,
    plus the two prime knobs. Guards against silent profile drift."""
    kk = rtp.load_profiles()["kk"]
    drops = {"ada_memory_search", "ada_remember", "ada_forget",
             "ada_session_recall", "web_search"}
    assert not drops & set(kk["include"])
    assert drops <= set(kk["exclude"])
    assert kk["env_knobs"]["ADA_PRIME_SKIP_HISTORY"] == "1"
    assert kk["env_knobs"]["ADA_SESSION_PRIME"] == "1"
    for keep in ("cms_read", "conv_journal", "wp_post", "cpt_post",
                 "calendar_read", "calendar_write", "tasks"):
        assert keep in kk["include"]
