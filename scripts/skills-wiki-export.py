#!/usr/bin/env python3
"""Render the ada-ocb skills inventory as an Education: lesson wikitext page.

Offline only — reads SKILL.md files from the repo and prints wikitext
(optionally to --out). Publishing is a separate, card-gated step through
the board-api /publish wiki-education sink; this script never calls a
network or holds wiki credentials.

  python3 scripts/skills-wiki-export.py
  python3 scripts/skills-wiki-export.py --out /tmp/skills-education.wiki
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts" / "board"))

import publication as pub  # noqa: E402  (pure, network-free helper)

TOPIC = "ada-ocb-skills"
SOURCE = "session-history"
LEVEL = "intro"
STATUS = "open"
NO_TH = True  # English-only page

SKILL_DIRS = (".agents/skills", ".opencode/skills")

# Recorded from the session history: when to invoke each skill in ada-ocb.
USAGE = {
    "ansible-first": "Triage host/fleet jobs for an existing playbook, then run the governed 9-step converge: check/diff, approval, backup, converge, verify, evidence.",
    "auto-kb": "Session-end capture of verified findings into docs/kb (MDDB-indexed); not for hypotheses.",
    "code-decision": "Jev decision door before applying a change with a construct/template/library/replacement choice; skip mechanical edits.",
    "docker-restart": "Restart the chaba web stack, with confirmation; verify localhost:8080/8081 after.",
    "git-status": "Quick branch / dirty-tree / diff / recent-commit summary when editing ada-ocb.",
    "health-check": "Deprecated: use the MCP health tools (check_health, get_alerts, restart_service) instead.",
    "info-find": "Unified retrieval across SSOT, code, MDDB, health, MCP and web, with citations.",
    "overnight-assessment": "Overnight Chaba assessment: health, GPU/queues, logs, ssot-validate, report.",
    "session-capture": "At handoff: route decisions, lessons and evidence to durable sinks with a handoff packet.",
    "ssot-search": "Find the canonical SSOT YAML key/path before reading the source.",
    "ssot-validate": "Validate SSOT YAML syntax/structure after edits.",
    "status": "Quick Working / Done / Remaining / Next-high-value summary.",
    "track4-smoke-test": "Quick navigation to the Track4 test page for smoke testing.",
    "wiki-education-publish": "Render -> card-gated /publish wiki-education -> /lesson source=wiki verify -> job yml record; never direct MediaWiki API.",
}

# Repositories explored in the same session history (plus their role here).
REPOS = [
    {
        "name": "tonezzz/chaba — ada-ocb worktree",
        "ref": "https://github.com/tonezzz/chaba",
        "role": "Ada-OCB control plane: SSOT, kanban, skills, board-api, wiki-education door",
        "use": "Holds the 11 SKILL.md files, inventory test, this exporter, the docs/kb entry and job trail; source of Education:Ada-Ocb-Skills",
    },
    {
        "name": "tonezzz/mddb — mddb-fork",
        "ref": "https://github.com/tonezzz/mddb",
        "role": "Markdown database with full-text/vector/hybrid search exposed over MCP",
        "use": "The mddb agent skill (search-tool choice, chunk projections, memory_*); chaba-lessons and KB indexing. Local lag snapshots: ~/var/tmp/mddb-lag-base and -fix",
    },
    {
        "name": "anthropics/claude-plugins-official",
        "ref": "https://github.com/anthropics/claude-plugins-official",
        "role": "Anthropic's official Claude Code plugin marketplace (plugins/, external_plugins/)",
        "use": "Installed skill-creator from plugins/skill-creator/skills/ into ~/.claude/skills with an OpenCode adaptation note; reference for portable skills/commands/agents. Apache-2.0, per-plugin LICENSE",
    },
]

BENCHMARK = {
    "name": "info-find efficiency A/B",
    "ref": "PR #219 — evals/info-find-efficiency/",
    "result": "8 offline tasks: direct grep 8/8 correct at ~92 narrow / 826 cross tokens vs info-find 0/8 at ~1700 tokens. Decision: keep info-find optional; no enforcement until routing improves. Card BEN-1359 closed.",
}

LESSON = {
    "name": "Build is not apply (2026-11-26)",
    "ref": "PR #229 / PR #236 — card OPS-1447",
    "result": "Adding deploy-runner-tools.yml was not convergence: only --check --diff had been run, so drift stayed live. Apply the playbook, install the schedule, then re-audit independently. The first timer install failed with BadUnitSetting because OnCalendar/Persistent/Unit were in [Unit] instead of [Timer] — validate user units with systemd-analyze --user verify before rollout. After PR #236 all hosts are in-sync, the daily timer is active, and the audit shows no DRIFT.",
}

FINDABILITY = {
    "name": "MDDB findability eval",
    "ref": "chaba-lessons — 3 eval queries",
    "result": "recall@5 / nDCG / MRR = 1.0 for all configs; FTS/bm25 ~5 ms p50 vs hybrid/vector ~1.6 s. Saved lessons are retrievable; keyword search is the cheap path.",
}

AUDIT_RULE = {
    "name": "Runner audit compares to controller pins",
    "ref": "PR #246 — ansible/playbooks/audit-runner-tools.yml",
    "result": "Installed sha256 must be compared to scripts/devin/runner-tooling.manifest.json pins, not each host's checkout; an ahead or stale checkout produced false DRIFT.",
}

SCHEDULES = {
    "name": "Scheduled automation",
    "ref": "fleet timer + monitor acfd73e3-04e7-43f9-82e5-bdc5635e3358",
    "result": "Daily runner-tools convergence timer on all managed hosts, plus a read-only 09:00 Asia/Bangkok SSOT/CI monitor covering ssot-validate-all, tooling pins, Cargo verifier and health/alerts.",
}

TOOLING2 = {
    "name": "build-mcp-server",
    "ref": "~/.claude/skills/build-mcp-server/ (from anthropics/claude-plugins-official)",
    "role": "Second ported plugin skill — MCP server design workflow with 8 bundled reference docs",
    "note": "Apache-2.0 LICENSE retained; OpenCode adaptation note covers Context7 fallback, board-api door for chaba mutations and {env:...} secrets in opencode.json.",
}

TOOLING = {
    "name": "ansible-first",
    "ref": ".agents/skills/ansible-first/SKILL.md (repo-canonical; ~/.claude/skills/ansible-first is a symlink on OpenCode hosts)",
    "role": "Global OpenCode skill — advertised before each model step for host/fleet/deploy/restart/provision tasks",
    "note": "30-second triage: skip for local/repo work; use board-api door for kanban/wiki/SSOT; check chaba ansible/ playbooks before ad-hoc SSH; --check --diff --limit, vault secrets, approval for disruptive plays.",
}


def _fm_block(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 4)
    return text[4:end] if end != -1 else ""


def _fm_value(lines: list[str], key: str) -> str:
    for i, line in enumerate(lines):
        if not line.startswith(key + ":"):
            continue
        value = line.split(":", 1)[1].strip()
        if value in (">", ">-", "|"):
            parts = []
            for nxt in lines[i + 1:]:
                if nxt and not nxt[0].isspace():
                    break
                if nxt.strip():
                    parts.append(nxt.strip())
            return " ".join(parts)
        return value.strip("'\"")
    return ""


def _fm_list(lines: list[str], key: str) -> list[str]:
    for i, line in enumerate(lines):
        if line.strip() == key + ":":
            out = []
            for nxt in lines[i + 1:]:
                if nxt and not nxt[0].isspace():
                    break
                m = re.match(r"\s*-\s+(.*)", nxt)
                if m:
                    out.append(m.group(1).strip().strip("'\""))
            return out
    return []


def parse_skill(path: Path, repo: Path) -> dict:
    """One SKILL.md -> {name, description, triggers, location, usage}."""
    text = path.read_text(encoding="utf-8")
    lines = _fm_block(text).splitlines()
    name = _fm_value(lines, "name") or path.parent.name
    description = _fm_value(lines, "description")
    if not description:
        # Frontmatter-less skills (auto-kb, overnight-assessment): first
        # non-heading body line after the title is the description.
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            description = line.strip()
            break
    description = re.sub(r"\*\*|`", "", description).replace("|", "&#124;")
    return {
        "name": name,
        "description": " ".join(description.split()),
        "triggers": ", ".join(_fm_list(lines, "triggers")) or "user/model (implicit)",
        "location": path.relative_to(repo).as_posix(),
        "usage": USAGE.get(name, ""),
    }


def collect_skills(repo: Path) -> list[dict]:
    skills = []
    for subdir in SKILL_DIRS:
        for path in sorted((repo / subdir).glob("*/SKILL.md")):
            skills.append(parse_skill(path, repo))
    return sorted(skills, key=lambda s: (s["name"], s["location"]))


def _cell(text: str) -> str:
    return " ".join(str(text or "").split()).replace("|", "&#124;")


def render_page(skills: list[dict], today: str, next_review: str,
                event_id: str) -> str:
    """Education: wikitext for the skill inventory (fixtures-only testable)."""
    title = pub.lesson_wiki_title(TOPIC)
    header = [
        "{{แม่แบบ:Education",
        f"|topic={TOPIC}",
        f"|level={LEVEL}",
        f"|source={SOURCE}",
        f"|learned_at={today}",
        f"|next_review={next_review}",
        f"|status={STATUS}",
        f"|updated={today}",
        f"|no_th={'1' if NO_TH else ''}",
        f"|event_id={event_id}",
        "}}", "",
        "Ada-OCB agent skills recorded from the 2026-11 session history. "
        "The inventory contract lives in "
        "[[chaba:tests/test_agents_skills_explored.py|test_agents_skills_explored.py]]; "
        "the full write-up lives in docs/kb/ada-ocb-skills-education.md.", "",
        f"This page covers {len(skills)} skills — "
        f"{sum(1 for s in skills if s['location'].startswith('.agents/'))} "
        "in .agents/skills and "
        f"{sum(1 for s in skills if s['location'].startswith('.opencode/'))} "
        "in .opencode/skills.", "",
        "== Inventory ==", "",
        '{| class="wikitable"',
        "! Skill !! Location !! Triggers !! Purpose / when to use",
    ]
    rows = []
    for s in skills:
        rows.extend([
            "|-",
            f"| {_cell(s['name'])} || {_cell(s['location'])} || "
            f"{_cell(s['triggers'])} || {_cell(s['description'])} — "
            f"{_cell(s['usage'])}",
        ])
    tail = [
        "|}", "",
        "== How to use in ada-ocb ==",
        "",
        "* Ask for a quick project state → ''status''; find a canonical SSOT key → ''ssot-search''; any broader question → ''info-find'' first.",
        "* After SSOT edits → ''ssot-validate''. At handoff → ''session-capture'' (durable sinks + handoff packet) and, for verified findings, ''auto-kb''.",
        "* Health questions use the MCP health tools directly — ''health-check'' is deprecated; ''docker-restart'' needs confirmation; ''track4-smoke-test'' and ''overnight-assessment'' are the smoke/overnight checks.",
        "",
        "== Repositories explored ==",
        "",
        "The same session history also explored these repositories (in addition to OpenCode's own documentation):",
        "",
        '{| class="wikitable"',
        "! Repository !! Reference !! Role !! How we used it",
    ]
    for repo in REPOS:
        tail.extend([
            "|-",
            f"| {_cell(repo['name'])} || {_cell(repo['ref'])} || "
            f"{_cell(repo['role'])} || {_cell(repo['use'])}",
        ])
    tail.extend([
        "|}", "",
        "== Benchmarks ==",
        "",
        f"* '''{_cell(BENCHMARK['name'])}''' — {_cell(BENCHMARK['ref'])}: "
        f"{_cell(BENCHMARK['result'])}",
        "*",
        f"* '''{_cell(LESSON['name'])}''' — {_cell(LESSON['ref'])}: "
        f"{_cell(LESSON['result'])}",
        "*",
        f"* '''{_cell(FINDABILITY['name'])}''' — {_cell(FINDABILITY['ref'])}: "
        f"{_cell(FINDABILITY['result'])}",
        "",
        "== Operations ==",
        "",
        f"* '''{_cell(AUDIT_RULE['name'])}''' — {_cell(AUDIT_RULE['ref'])}: "
        f"{_cell(AUDIT_RULE['result'])}",
        "*",
        f"* '''{_cell(SCHEDULES['name'])}''' — {_cell(SCHEDULES['ref'])}: "
        f"{_cell(SCHEDULES['result'])}",
        "",
        "== Related tooling ==",
        "",
        f"* '''{_cell(TOOLING['name'])}''' — {_cell(TOOLING['ref'])}: "
        f"{_cell(TOOLING['role'])}. {_cell(TOOLING['note'])}",
        "*",
        f"* '''{_cell(TOOLING2['name'])}''' — {_cell(TOOLING2['ref'])}: "
        f"{_cell(TOOLING2['role'])}. {_cell(TOOLING2['note'])}",
        "",
        "[[Category:Education]]",
        "[[Category:Education/Level/intro]]",
        "[[Category:Education/Status/open]]",
        f"[[Category:Education/Topics/{pub._topic_slug(TOPIC)}]]",
    ])
    return "\n".join(header + rows + tail) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=REPO,
                    help="ada-ocb worktree containing .agents/skills")
    ap.add_argument("--out", type=Path, help="write wikitext here (else stdout)")
    ap.add_argument("--today", default="2026-11-24")
    ap.add_argument("--next-review", default="2026-12-08")
    ap.add_argument("--event-id", default="skills-wiki-export-2026-11-24")
    args = ap.parse_args()

    skills = collect_skills(args.repo)
    page = render_page(skills, args.today, args.next_review, args.event_id)
    if args.out:
        args.out.write_text(page, encoding="utf-8")
        print(f"wrote {len(skills)} skills -> {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(page)


if __name__ == "__main__":
    main()
