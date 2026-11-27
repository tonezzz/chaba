# Dispatch outcome — ai-forge skills → Education:Ada-Ocb-Skills (2026-11-27)

Card: `ai-forge-skills-wiki-education-2026-11-27` (DEV-1499)

## What changed

- **Evaluated** `ansible-community/ai-forge` @ `28a9a58` (cloned to /tmp, read-only): 40 `SKILL.md` files across 7 Lola marketplace modules — collection SDLC (commit, changelog-fragment, create-pr, release/stable-release, sonarcloud-*, run-tests, sanity, tox-lint, security-scan, docs-generate), standards (`ansible-zen`), content-development (`write-content`, `write-module`, `write-content-tests`, `write-module-tests`), documentation (`ansible-markdown-docs`), cloud (aws-terminator-*), network triage, plus repo `.agents/skills` (`pr-new`, `pr-contributor-review`, `check-skill-spec`). License: **GPL-3.0**.
- **Verdict**: pointer-first, no install. The collection-SDLC half is N/A to chaba (not an Ansible collection — no galaxy.yml/changelog/antsibull/SonarCloud). Kept as reference candidates: `write-content` (CoP playbook/role authoring patterns transfer to chaba `ansible/`) and `ansible-markdown-docs` (docs.ansible.com as Markdown). GPL-3.0 means ideas may inform chaba skills but skill text must not be copied verbatim.
- `scripts/skills-wiki-export.py`: added ai-forge to `REPOS` and a new `AIFORGE_EVAL` block rendered as an "External evaluation" section.
- `docs/kb/ada-ocb-skills-education.md`: added ai-forge row to the repositories table + "External evaluation — ansible-community/ai-forge (2026-11-27)" section; bumped `updated:`.
- `docs/ssot/jobs/education/2026-11-24-skills-wiki-education.yml`: appended DONE verify lines with revid/receipt.

## Publish + verify (via board-api door only — no direct MediaWiki API)

- Render: `python3 scripts/skills-wiki-export.py --out /tmp/opencode/ada-ocb-skills-ai-forge.wiki --today 2026-11-27 --next-review 2026-12-11 --event-id skills-wiki-export-2026-11-27-ai-forge` → 14 skills, 10,663 bytes.
- `POST /publish` kind=lesson, sinks=["wiki-education"], visibility=private, meta.format=wikitext, meta.wiki_title=Education:Ada-Ocb-Skills → **delivered, pageid 333, revid 813** (event `skills-wiki-export-2026-11-27-ai-forge`, idempotency_key same).
- `POST /lesson {op:get, source:wiki, topic:ada-ocb-skills}` → slug `lesson-d8b6938588d3`; content confirms learned_at=2026-11-27, next_review=2026-12-11, the new event_id, the "External evaluation" section and 7 ai-forge mentions.
- Contract tests: 6/6 pass (run manually — pytest not installed on this host).

## How to verify

- `POST /lesson {"op":"get","source":"wiki","topic":"ada-ocb-skills"}` on `https://idc03.taila0626a.ts.net:10000` — check for "External evaluation" + `ai-forge`.
- `git show` this branch's diff on the three files above.
- Live page (staff SSO): `https://wiki.h3.gizmo-thailand.com/index.php?title=Education:Ada-Ocb-Skills`

lessons:
- `/publish` routes through `job_actor`: the event body needs an explicit `"from":"devin"` (or another ACTORS/daemon name); without it the verified caller identity (email) fails validation with 400 "from must be an actor or a host/daemon name".
- ai-forge is GPL-3.0 — evaluate upstream skill repos for license before porting text; reference/pointer use is fine, verbatim copies are not.
- pytest is not installed on dispatch hosts; run `tests/test_agents_skills_explored.py` functions manually via importlib when needed.
