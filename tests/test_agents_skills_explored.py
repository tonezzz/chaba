"""Contract + wiki-export tests for the skills explored in session history.

The inventory was discovered in ada-ocb's `.agents/skills/` and
`.opencode/skills/`; the wiki-export tests prove the Education: page can be
rendered offline, from fixtures, before any card-gated publish.
"""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO / ".agents" / "skills"
SESSION_SKILLS_DIR = REPO / ".opencode" / "skills"

_spec = importlib.util.spec_from_file_location(
    "skills_wiki_export", REPO / "scripts" / "skills-wiki-export.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

EXPLORED_SKILLS = {
    "ansible-first",
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


def test_each_skill_has_name_and_description():
    skills = export.collect_skills(REPO)
    # Pin the skills explored in session history; newer skills may be added.
    assert (EXPLORED_SKILLS | EXPLORED_SESSION_SKILLS) <= {
        s["name"] for s in skills}
    for skill in skills:
        assert (REPO / skill["location"]).exists(), skill
        assert len(skill["description"]) > 10, skill
        assert skill["triggers"] and skill["usage"], skill


def test_parse_skill_without_frontmatter_fixture():
    # Legacy skills without frontmatter still parse from the first body line.
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        path = repo / ".agents" / "skills" / "plain-skill" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "# Plain Skill\n\nA verified finding with a durable sink.\n",
            encoding="utf-8")
        skill = export.parse_skill(path, repo)
    assert skill["name"] == "plain-skill"
    assert skill["description"] == "A verified finding with a durable sink."
    assert skill["triggers"] == "user/model (implicit)"


def test_wiki_export_shape_with_fixtures():
    fixtures = [
        {"name": "one", "description": "First purpose.", "triggers": "user",
         "location": ".agents/skills/one/SKILL.md", "usage": "Use first."},
        {"name": "two", "description": "Second purpose.", "triggers": "model",
         "location": ".opencode/skills/two/SKILL.md", "usage": "Use second."},
    ]
    page = export.render_page(
        fixtures, "2026-11-24", "2026-12-08", "test-event")
    assert "{{แม่แบบ:Education" in page
    for param in ("|topic=ada-ocb-skills", "|level=intro",
                  "|source=session-history", "|learned_at=2026-11-24",
                  "|next_review=2026-12-08", "|event_id=test-event"):
        assert param in page, param
    assert "== Inventory ==" in page
    assert "== Repositories explored ==" in page
    assert "== Benchmarks ==" in page and "info-find efficiency A/B" in page
    assert "Build is not apply" in page and "OPS-1447" in page
    assert "== Related tooling ==" in page and "ansible-first" in page
    assert page.count("\n|-") == len(fixtures) + len(export.REPOS)
    for repo in export.REPOS:
        assert repo["name"] in page, repo["name"]
        assert repo["ref"] in page, repo["name"]
    assert "[[Category:Education]]" in page
    assert "[[Category:Education/Topics/ada-ocb-skills]]" in page
    assert "Use first." in page and "Use second." in page


def test_wiki_export_covers_all_explored_skills():
    skills = export.collect_skills(REPO)
    page = export.render_page(
        skills, "2026-11-24", "2026-12-08", "skills-wiki-export-2026-11-24")
    for skill in skills:
        assert skill["name"] in page, skill["name"]
        assert skill["usage"] in page, skill["name"]
    assert page.count("\n|-") == len(skills) + len(export.REPOS)
