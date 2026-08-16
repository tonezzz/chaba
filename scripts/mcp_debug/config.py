"""MCP Debug configuration and shared state."""
import logging
import yaml
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"
REPORTS_SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.reports.yml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

with open(SSOT) as f:
    CONFIG = yaml.safe_load(f)

HOSTS = CONFIG.get("hosts", {})
DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
RAW_PREFIXES = CONFIG.get("raw_commands", {}).get("allowed_prefixes", [])
PRESETS = CONFIG.get("presets", {})
PRESET_DESCRIPTIONS = {name: data.get("description", "") for name, data in PRESETS.items()}


def load_report_config():
    if not REPORTS_SSOT.exists():
        return {}
    with open(REPORTS_SSOT) as f:
        return yaml.safe_load(f) or {}


def reload_config():
    global CONFIG, HOSTS, DEBUG_COMMANDS, RAW_PREFIXES, PRESETS, PRESET_DESCRIPTIONS
    with open(SSOT) as f:
        CONFIG = yaml.safe_load(f)
    HOSTS = CONFIG.get("hosts", {})
    DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
    RAW_PREFIXES = CONFIG.get("raw_commands", {}).get("allowed_prefixes", [])
    PRESETS = CONFIG.get("presets", {})
    PRESET_DESCRIPTIONS = {name: data.get("description", "") for name, data in PRESETS.items()}
