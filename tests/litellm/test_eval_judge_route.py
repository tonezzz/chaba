"""Config asserts for the eval-judge lane (card gemini-eval-judge-lane).

The lane exists to give NEW bulk eval/judge work a paid-first path that
CANNOT silently retry into the rate-limited free tier (the OPS-1255
run-2 failure mode). litellm 1.105 resolves router fallbacks
recursively, so legs are pinned as dict entries carrying
disable_fallbacks:true — the effective chain is exactly the three
listed hops and then the caller fails closed.
"""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "stacks/idc03/litellm/config.yaml"

EXPECTED_LEGS = ["gemini-3.5-flash-lite",
                 "ollama-llama32-3b-kkmac",
                 "colab-gemma3"]


def _config():
    return yaml.safe_load(CONFIG.read_text())


def _eval_judge_fallbacks(config):
    for item in config["router_settings"]["fallbacks"]:
        if "eval-judge" in item:
            return item["eval-judge"]
    raise AssertionError("eval-judge missing from router_settings.fallbacks")


def _leg_name(leg):
    return leg["model"] if isinstance(leg, dict) else leg


def test_eval_judge_model_entry_is_paid_flash_lite():
    config = _config()
    entries = [m for m in config["model_list"]
               if m["model_name"] == "eval-judge"]
    assert len(entries) == 1
    params = entries[0]["litellm_params"]
    assert params["model"] == "gemini/gemini-3.5-flash-lite"
    assert params["api_key"] == "os.environ/GEMINI_API_KEY_PAID"


def test_eval_judge_chain_paid_first_local_last_no_free():
    config = _config()
    legs = _eval_judge_fallbacks(config)
    names = [_leg_name(l) for l in legs]
    assert names == EXPECTED_LEGS
    assert names[0] == "gemini-3.5-flash-lite"  # paid gemini leg first
    for name in names:
        assert ":free" not in name
        assert not name.startswith("or-free")
        assert not name.endswith("-free")


def test_eval_judge_legs_disable_nested_fallbacks():
    """Every leg must pin disable_fallbacks — otherwise a failed leg
    recursively expands into its own chain (e.g. gemini-3.5-flash-lite
    -> gemini-3.5-flash-lite-free), which is the free-tier path this
    lane exists to avoid."""
    legs = _eval_judge_fallbacks(_config())
    for leg in legs:
        assert isinstance(leg, dict), (
            f"eval-judge leg {leg!r} must be a dict pinning "
            "disable_fallbacks:true (nested fallback expansion)")
        assert leg.get("disable_fallbacks") is True


def test_eval_judge_fallback_targets_exist():
    config = _config()
    names = {m["model_name"] for m in config["model_list"]}
    for leg in _eval_judge_fallbacks(config):
        assert _leg_name(leg) in names


def test_ops1255_canary_untouched():
    """Regression assert: the OPS-1255 nemotron canary route and the
    or-free-* group must be unchanged by this lane."""
    config = _config()
    by_name = {m["model_name"]: m["litellm_params"]
               for m in config["model_list"]}
    assert by_name["or-free-nemotron-ultra"]["model"] == (
        "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free")
    # or-free-nemotron-ultra must not appear in eval-judge's chain
    legs = {_leg_name(l) for l in _eval_judge_fallbacks(config)}
    assert not any("or-free" in l or ":free" in l for l in legs)
