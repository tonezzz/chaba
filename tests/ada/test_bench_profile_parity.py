"""Parity + delta assertions for the kk CMS-only bench profiles.

MEM-0498 / step 2 of the 2026-11-24 CMS-only re-test plan.

persons.kk.tools is the production surface. kk-parity must be an exact
copy: a stale "restore" profile silently changes the dev lane after a
bench run and invalidates every before/after comparison. kk-cms-only must
be production MINUS the declared experimental drops, PLUS the documented
test-only seed writers; any other delta is drift.

No network, no live hosts — pure SSOT YAML assertions.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SSOT = REPO / "docs/ssot/apps/ssot.apps.ada-persons.yml"

MEMORY_TOOLS = {
    "ada_memory_search", "ada_remember", "ada_forget", "ada_session_recall",
}
EXPERIMENT_DROPS = MEMORY_TOOLS | {"web_search"}
# Prod dropped this 2026-10-14 (wrong-system trap; wp_post owns writes).
# It survives in the bench profile only to seed kk_cms_only_seeded_recall;
# the scenario's cleanup removes the page and tests/benchmark.yml
# write_allowed_in restricts the tool to that scenario.
TEST_ONLY_WRITERS = {"cms_publish_page"}
BENCH_PROFILES = ("kk-cms-only", "kk-parity")


def _data() -> dict:
    return yaml.safe_load(SSOT.read_text())


def _prod() -> dict:
    return _data()["persons"]["kk"]["tools"]


def _profile(name: str) -> dict:
    return _data()["bench_profiles"][name]


def test_parity_is_exact_prod_surface() -> None:
    prod, parity = _prod(), _profile("kk-parity")
    assert set(parity["include"]) == set(prod["include"]), (
        "kk-parity include drifted from persons.kk.tools: "
        f"missing={sorted(set(prod['include']) - set(parity['include']))}, "
        f"extra={sorted(set(parity['include']) - set(prod['include']))}"
    )
    assert set(parity["exclude"]) == set(prod["exclude"]), (
        "kk-parity exclude drifted from persons.kk.tools: "
        f"missing={sorted(set(prod['exclude']) - set(parity['exclude']))}, "
        f"extra={sorted(set(parity['exclude']) - set(prod['exclude']))}"
    )
    # Set equality alone would hide a duplicate entry.
    assert len(parity["include"]) == len(prod["include"])
    assert len(parity["exclude"]) == len(prod["exclude"])


def test_cms_only_is_prod_minus_declared_drops() -> None:
    prod, exp = _prod(), _profile("kk-cms-only")
    want_include = (set(prod["include"]) - EXPERIMENT_DROPS) | TEST_ONLY_WRITERS
    want_exclude = (set(prod["exclude"]) | EXPERIMENT_DROPS) - TEST_ONLY_WRITERS
    assert set(exp["include"]) == want_include, (
        "kk-cms-only include drifted from prod-minus-experiment: "
        f"missing={sorted(want_include - set(exp['include']))}, "
        f"unexpected={sorted(set(exp['include']) - want_include)}"
    )
    assert set(exp["exclude"]) == want_exclude, (
        "kk-cms-only exclude drifted from prod-plus-experiment: "
        f"missing={sorted(want_exclude - set(exp['exclude']))}, "
        f"unexpected={sorted(set(exp['exclude']) - want_exclude)}"
    )


def test_session_prime_knob_matches_profile_purpose() -> None:
    assert _profile("kk-cms-only")["env_knobs"]["ADA_SESSION_PRIME"] == "0"
    assert _profile("kk-parity")["env_knobs"]["ADA_SESSION_PRIME"] == "1"


def test_no_tool_is_both_included_and_excluded() -> None:
    for name in BENCH_PROFILES:
        prof = _profile(name)
        clash = set(prof["include"]) & set(prof["exclude"])
        assert not clash, f"{name}: in both lists: {sorted(clash)}"


def test_bench_profiles_target_dev_lane_only() -> None:
    for name in BENCH_PROFILES:
        prof = _profile(name)
        assert prof["instance"] == "kk-dev", f"{name}: wrong instance"
        assert prof["host"] == "idc03", f"{name}: wrong host"
        assert prof["env_file"].endswith("-dev.env"), (
            f"{name}: bench profile must never target a prod env file"
        )
