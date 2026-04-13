"""Config API endpoints."""
from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/config/voice_commands")
@router.get("/jarvis/api/config/voice_commands")
async def get_voice_commands_config() -> dict[str, Any]:
    """Get voice command configuration for frontend."""
    return {
        "config": {
            "enabled": True,
            "reload": {
                "enabled": True,
                "phrases": [
                    "reload system",
                    "reload sheets",
                    "reset system",
                    "restart system",
                    "รีโหลด",
                    "รีเฟรช",
                    "รีเซ็ต",
                    "รีสตาร์ท",
                ],
                "mode_keywords": {
                    "gems": ["gems", "gem", "models", "model", "เจม", "โมเดล"],
                    "knowledge": ["knowledge", "kb", "know", "ความรู้"],
                    "memory": ["memory", "mem", "เมม", "เมมโม"],
                },
            },
            "reminders_add": {
                "enabled": True,
            },
            "gems_list": {
                "enabled": True,
            },
        }
    }
