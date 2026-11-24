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
| `auto-kb` | `.agents/skills` | session end | Verified findings → `docs/kb/` entries → MDDB; never for hypotheses or session narrative. |
| `session-capture` | `.opencode/skills` | session end/handoff | Route decisions, lessons and evidence to durable sinks (card, SSOT, docs/kb) and write a handoff packet. |
| `git-status` | `.agents/skills` | user | Branch / dirty tree / diff / recent commits when editing ada-ocb. |
| `docker-restart` | `.agents/skills` | user | Restart the chaba web stack with confirmation; verify `localhost:8080` / `8081`. |
| `health-check` | `.agents/skills` | user, model | Deprecated — use MCP health tools (`check_health`, `get_alerts`, `restart_service`) directly. |
| `track4-smoke-test` | `.agents/skills` | user | Navigate to the Track4 test page for a quick smoke check. |
| `overnight-assessment` | `.agents/skills` | user | Overnight Chaba assessment: health, GPU/queues, logs, SSOT check, report. |

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

Run: `python3 -m pytest tests/test_agents_skills_explored.py -q` (6 passed at creation).

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
