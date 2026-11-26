from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "stacks/idc03/litellm/config.yaml"


def test_consult_aliases_have_single_explicit_routes_without_fallbacks():
    config = yaml.safe_load(CONFIG.read_text())
    models = {item["model_name"]: item["litellm_params"]
              for item in config["model_list"]}
    fallbacks = config["router_settings"]["fallbacks"]
    fallback_sources = {next(iter(item)) for item in fallbacks}
    fallback_targets = {
        target for item in fallbacks for targets in item.values()
        for target in targets
    }

    expected = {
        "consult-flash": (
            "gemini/gemini-3.5-flash",
            "os.environ/GEMINI_API_KEY_PAID",
        ),
        "consult-pro": (
            "gemini/gemini-3.1-pro-preview",
            "os.environ/GEMINI_API_KEY_PAID",
        ),
        "consult-claude": (
            "openrouter/anthropic/claude-fable-5.1",
            "os.environ/OPENROUTER_API_KEY",
        ),
    }

    for alias, (model, key) in expected.items():
        assert models[alias]["model"] == model
        assert models[alias]["api_key"] == key
        assert alias not in fallback_sources
        assert alias not in fallback_targets
