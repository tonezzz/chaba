"""Skills explored from this session's history (ada-ocb).

The set below was discovered from the session where the skills in
`.agents/skills/` and `.opencode/skills/` were listed and how they should be
used in ada-ocb. The test pins the list so it can be re-run later.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / ".agents" / "skills"
SESSION_SKILLS_DIR = REPO / ".opencode" / "skills"

EXPLORED_SKILLS = {
    "auto-kb",
    "docker-restart",
    "git-status",
    "health-check",
    "info-find",
    "overnight-assessment",
    "ssot-search",
    "ssot-validate",
    "status",
    "track4-smoke-test",
}

EXPLORED_SESSION_SKILLS = {
    "session-capture",
}


def test_explored_skills_exist():
    missing = sorted(
        name for name in EXPLORED_SKILLS
        if not (SKILLS_DIR / name / "SKILL.md").exists()
    )
    assert not missing, f"skills not found under {SKILLS_DIR}: {missing}"


def test_explored_session_skills_exist():
    missing = sorted(
        name for name in EXPLORED_SESSION_SKILLS
        if not (SESSION_SKILLS_DIR / name / "SKILL.md").exists()
    )
    assert not missing, f"skills not found under {SESSION_SKILLS_DIR}: {missing}"
