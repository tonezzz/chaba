"""MCP Debug configuration and shared state."""
import logging
import yaml
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent.parent
SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.yml"
BASELINES = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.baselines.yml"
FILES_SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.files.yml"
REPORTS_SSOT = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.mcp-debug.reports.yml"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

with open(SSOT) as f:
    CONFIG = yaml.safe_load(f)

FILE_CONFIG = {}
if FILES_SSOT.exists():
    with open(FILES_SSOT) as f:
        FILE_CONFIG = yaml.safe_load(f) or {}

RAW_COMMANDS_SSOT = REPO_DIR / (CONFIG.get("raw_commands_source") or "docs/ssot/infrastructure/ssot.mcp-debug.raw-commands.yml")
RAW_COMMANDS = (yaml.safe_load(open(RAW_COMMANDS_SSOT)) or {}) if RAW_COMMANDS_SSOT.exists() else {}

def _load_log_units():
    units = []
    home_path = REPO_DIR / "docs" / "ssot" / "infrastructure" / "ssot.health.home.yml"
    if not home_path.exists():
        return units
    with open(home_path) as f:
        home = yaml.safe_load(f) or {}
    for cat in home.get("categories", []):
        cat_file = REPO_DIR / cat.get("file", "")
        if not cat_file.exists():
            continue
        with open(cat_file) as f:
            data = yaml.safe_load(f) or {}
        for item in data.get("services", []):
            if item.get("type") == "systemd" and item.get("service"):
                units.append({
                    "id": item.get("id", ""),
                    "host": item.get("host", "tony_omen"),
                    "service": item["service"],
                    "name": item.get("name", ""),
                })
    return units

HOSTS = CONFIG.get("hosts", {})
DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
RAW_PREFIXES = RAW_COMMANDS.get("raw_commands", {}).get("allowed_prefixes", [])
RAW_CATEGORIES = RAW_COMMANDS.get("raw_commands", {}).get("categories", {})
PRESETS = CONFIG.get("presets", {})
LOG_UNITS = _load_log_units()
PRESET_DESCRIPTIONS = {name: data.get("description", "") for name, data in PRESETS.items()}
TABLE_SCHEMAS = CONFIG.get("output_formats", {}).get("table_schemas", {})
FILE_LIMITS = FILE_CONFIG.get("limits", {})
FILE_TOOLS = FILE_CONFIG.get("tools", {})


def load_report_config():
    if not REPORTS_SSOT.exists():
        return {}
    with open(REPORTS_SSOT) as f:
        return yaml.safe_load(f) or {}


def reload_config():
    global CONFIG, HOSTS, DEBUG_COMMANDS, RAW_PREFIXES, RAW_CATEGORIES, RAW_COMMANDS, PRESETS, PRESET_DESCRIPTIONS
    with open(SSOT) as f:
        CONFIG = yaml.safe_load(f)
    raw_path = REPO_DIR / (CONFIG.get("raw_commands_source") or "docs/ssot/infrastructure/ssot.mcp-debug.raw-commands.yml")
    RAW_COMMANDS = (yaml.safe_load(open(raw_path)) or {}) if raw_path.exists() else {}
    HOSTS = CONFIG.get("hosts", {})
    DEBUG_COMMANDS = CONFIG.get("debug_commands", {})
    RAW_PREFIXES = RAW_COMMANDS.get("raw_commands", {}).get("allowed_prefixes", [])
    RAW_CATEGORIES = RAW_COMMANDS.get("raw_commands", {}).get("categories", {})
    PRESETS = CONFIG.get("presets", {})
    PRESET_DESCRIPTIONS = {name: data.get("description", "") for name, data in PRESETS.items()}
