---
category: operations
type: education
status: defined
title: Ada-OCB — Agent Skills Inventory and How to Use Them
description: The eleven skills discovered in the ada-ocb worktree (.agents/skills and .opencode/skills), the offline contract test that pins them, and how each one is used in ada-ocb. Recorded from session history 2026-11-24.
tags: [ada, ada-ocb, skills, education, ssot, wiki, testing, session-history, chaba]
created: 2026-11-24
updated: 2026-11-24
related:
  - tests/test_agents_skills_explored.py
  - scripts/skills-wiki-export.py
  - docs/ssot/jobs/education/2026-11-24-skills-wiki-education.yml
  - ada-ocb-tools-mcp-workflow-education.md
search_keywords: [ada-ocb, skills, SKILL.md, agents/skills, opencode/skills, session-capture, info-find, ssot-search, ssot-validate, auto-kb, wiki education, Education:Ada-Ocb-Skills, test contract, inventory]
---

# Ada-OCB — Agent Skills Inventory and How to Use Them

**Abstract**: ada-ocb carries two skill surfaces — ten skills under `.agents/skills/` and one under `.opencode/skills/`. This entry records the inventory discovered from session history, the offline contract test that pins it (`tests/test_agents_skills_explored.py`), the wikitext exporter (`scripts/skills-wiki-export.py`), and the wiki-education publish path (card-gated, through board-api).

## Inventory (11 skills)

| Skill | Source | Trigger | Purpose / when to use in ada-ocb |
| ----- | ------ | ------- | -------------------------------- |
| `status` | `.agents/skills` | user, model | Quick Working / Done / Remaining / Next-high-value summary when asked "where are we". |
| `info-find` | `.agents/skills` | user, model | Unified retrieval across SSOT, code, MDDB, health, MCP and web, with citations; first stop for "how is X defined / find X". |
| `ssot-search` | `.agents/skills` | user, model | Find the canonical SSOT YAML key/path before reading the source. |
| `ssot-validate` | `.agents/skills` | user, model | Validate SSOT YAML syntax/structure after edits. |
| `ansible-first` | `.agents/skills` | user, model | Ansible-first triage + governed 9-step fleet-change procedure: locate playbook, check/diff, approval, backup, converge, verify, file evidence. |
| `auto-kb` | `.agents/skills` | session end | Verified findings → `docs/kb/` entries → MDDB; never for hypotheses or session narrative. |
| `session-capture` | `.opencode/skills` | session end/handoff | Route decisions, lessons and evidence to durable sinks (card, SSOT, docs/kb) and write a handoff packet. |
| `git-status` | `.agents/skills` | user | Branch / dirty tree / diff / recent commits when editing ada-ocb. |
| `docker-restart` | `.agents/skills` | user | Restart the chaba web stack with confirmation; verify `localhost:8080` / `8081`. |
| `health-check` | `.agents/skills` | user, model | Deprecated — use MCP health tools (`check_health`, `get_alerts`, `restart_service`) directly. |
| `track4-smoke-test` | `.agents/skills` | user | Navigate to the Track4 test page for a quick smoke check. |
| `overnight-assessment` | `.agents/skills` | user | Overnight Chaba assessment: health, GPU/queues, logs, SSOT check, report. |
| `wiki-education-publish` | `.opencode/skills` | user, model | Card-gated render → `/publish` `wiki-education` → `/lesson source=wiki` verify → job-yml record; never direct MediaWiki API. Created 2026-11-24 from this session history with the `skill-creator` skill. |

`auto-kb` and `overnight-assessment` gained `description` frontmatter on 2026-11-24 so OpenCode advertises them in this session; the test fixture still covers the frontmatter-less shape for legacy skills.

## Retrieval path

1. `tests/test_agents_skills_explored.py` — canonical inventory contract; `export.collect_skills(REPO)` reads all 11 `SKILL.md` files.
2. `scripts/skills-wiki-export.py` — offline wikitext renderer; `render_page(...)` is fixture-testable, no network.
3. `docs/kb/ada-ocb-skills-education.md` — this pointer-first write-up; SSOT keeps only a verdict row + `ref:` link.

## Test contract

- `test_explored_skills_exist` / `test_explored_session_skills_exist` — pin the 10 + 1 skill directories.
- `test_each_skill_has_name_and_description` — every skill resolves to a real file with a name, description, trigger and usage note.
- `test_parse_skill_without_frontmatter_fixture` — the frontmatter-less shape stays supported.
- `test_wiki_export_shape_with_fixtures` — Education: template params, inventory table, categories and usage notes render offline.
- `test_wiki_export_covers_all_explored_skills` — the generated page mentions all 11 skills.

Run: `python3 -m pytest tests/test_agents_skills_explored.py -q` (6 passed; still 6 passed on current master, which added `code-decision` — the pin is a subset assertion).

`skill-creator` eval (2026-11-24): two simulated test cases (republish-after-change, verify-only-no-write), 3 assertions each, all 6 passed in an inline run; the four baseline subagents were unavailable due to model rate limits/cooldowns, so per skill-creator's no-subagent adaptation the baselines were skipped. Static review viewer: `/tmp/opencode/wiki-education-publish-review.html`. Human review: approved, no changes requested.

## Repositories explored

Recorded alongside the skills in the same session history; the wiki page carries the same table.

| Repository | Role | How we used it |
| ---------- | ---- | -------------- |
| `tonezzz/chaba` (ada-ocb worktree, https://github.com/tonezzz/chaba) | Ada-OCB control plane: SSOT, kanban, skills, board-api, wiki-education door | Holds the 11 `SKILL.md` files, inventory test, `scripts/skills-wiki-export.py`, this entry and the job trail; source of `Education:Ada-Ocb-Skills`. |
| `tonezzz/mddb` (mddb-fork, https://github.com/tonezzz/mddb) | Markdown database with full-text/vector/hybrid search over MCP | The `mddb` agent skill (search-tool choice, chunk projections, `memory_*`); `chaba-lessons` / KB indexing. Local lag snapshots: `~/var/tmp/mddb-lag-base` and `-fix`. |
| `anthropics/claude-plugins-official` (https://github.com/anthropics/claude-plugins-official) | Anthropic's official Claude Code plugin marketplace (`plugins/`, `external_plugins/`) | Installed `skill-creator` from `plugins/skill-creator/skills/` into `~/.claude/skills/skill-creator` with an OpenCode adaptation note; reference for portable skills/commands/agents. Apache-2.0, per-plugin `LICENSE`. |

## Benchmarks

- **info-find efficiency A/B** (PR #219, `evals/info-find-efficiency/`, card `BEN-1359` closed): 8 offline tasks comparing `info-find` to bounded direct grep. Medians: narrow — info-find ~1703 tokens / 7616 ms vs direct ~92 tokens / 18 ms; cross — info-find ~1699 tokens / 5487 ms vs direct ~826 tokens / 305 ms. Correctness 0/8 vs 8/8 after hydrating top local paths. Decision rule (cross-source adoption only at ≤70% tokens with equal correctness) was not met: **keep `info-find` optional**, revisit with better routing/queries. Directional evidence only (offline, 8 tasks, bytes/4 token proxy).

### Build is not apply (2026-11-26)

PR #229 added `ansible/playbooks/deploy-runner-tools.yml`, the check→apply wrapper and the daily timer installer — but only `--check --diff` was run, so fleet drift stayed live. Adding a playbook is not convergence: apply it, install the schedule, then re-audit with an independent check. The first timer install was rejected by all hosts with `BadUnitSetting` because `OnCalendar`/`Persistent`/`Unit` were in `[Unit]` instead of `[Timer]`; validate user units with `systemd-analyze --user verify` before rollout. PR #236 fixed the unit; after apply every host reported in-sync, the timer is active, and the re-audit shows no `DRIFT` (only expected `kk-mac` `MISSING-DEST`). Card `OPS-1447` filed and closed. The full lesson is in MDDB `chaba-lessons/ocb-efficiency-lessons-2026-11-25` and the OpenChamber knowledge note.

## Related tooling

- **`ansible-first`** (`.agents/skills/ansible-first/SKILL.md`, repo-canonical; `~/.claude/skills/ansible-first` is a symlink on OpenCode hosts): global OpenCode skill, advertised before each model step. 30-second triage — skip for local/repo work, use the board-api write door for kanban/wiki/SSOT mutations, and for remote/fleet/repeatable config check chaba's `ansible/` playbooks (and `~/ansible`) before ad-hoc SSH. Preflight with `--check --diff --limit`, keep secrets in vault files, require approval for disruptive plays, record where filed.

## Wiki education record

The generated page is `Education:Ada-Ocb-Skills` (`pub.lesson_wiki_title("ada-ocb-skills")`), carrying the standard `แม่แบบ:Education` call with `topic=ada-ocb-skills`, `source=session-history`, `learned_at=2026-11-24`, `next_review=2026-12-08`, and `[[Category:Education]]`. Publish is a separate, card-gated step:

```bash
python3 scripts/skills-wiki-export.py --out /tmp/ada-ocb-skills.wiki
# then, on an authorized card: POST /publish sinks=["wiki-education"] (board-api door)
```

Do not call the MediaWiki API directly; the door owns wiki writes, the idempotency key dedupes reruns, and failed writes queue to the publication outbox. Keep private content under `wiki-private` / `PrivateNews:`. Topic family convention (AGENTS.md): this is the hub lesson for `ada-ocb-skills-*`; upsert in place — don't fork a new topic.

## Guardrails

- Pointer-first: no copied SSOT bodies, no secrets, no stale volatile state.
- Wiki reads go through `/lesson source=wiki`; a door that doesn't echo `source:"wiki"` must fail loudly.
- Education prose lives in wiki lessons and `docs/kb`; SSOT keeps only the verdict row + pointer link.
