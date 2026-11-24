---
name: wiki-education-publish
description: Publish, republish or verify an Education: lesson on wiki.h3 through the board-api wiki-education door, then record the receipt in the ada-ocb job yml. Use this skill whenever a wiki education page must be created or refreshed after skill/doc changes, or when someone asks whether an Education lesson is live — even if they do not name the wiki or the door. Never call the MediaWiki API directly.
---

# Wiki education publish

This is the ada-ocb path from a local skill/doc change to a live `Education:` lesson and a durable evidence record. The board-api owns every wiki write and all credentials; this skill only renders content and calls the door.

## When to use

- A skill, `docs/kb` entry or job trail changed and the corresponding `Education:` page is stale.
- A new Education lesson needs to land from repo content.
- Someone asks "is the wiki page current?" or "what revision is live?".

## Preconditions

1. A kanban card authorizes the wiki write (e.g. `ADA-0031` did for `Education:Ada-Ocb-Skills`). If there is no card, file one first — an unrecorded write does not exist.
2. Work in an ada-ocb worktree that contains `scripts/skills-wiki-export.py` and `docs/ssot/jobs/education/<job>.yml`.
3. Use the board-api door over SSH on idc03 (`board-cli.py __api`), or any transport that reaches the same localhost service. The door binds `127.0.0.1:8787` there.

## Steps

1. **Render offline.** `python3 scripts/skills-wiki-export.py --out <temp-file>` (or the repo's renderer for another lesson). Confirm the `แม่แบบ:Education` call, `topic`, categories and the changed content appear in the wikitext. This step never touches the network.
2. **Publish through the door.** `POST /publish` with `kind=lesson`, `visibility=private`, `sinks=["wiki-education"]`, `body=<wikitext>`, `meta.format=wikitext` plus `topic/level/source/learned_at/next_review/status/no_th`, and `meta.wiki_title=Education:<Title>`. For a republish, use a **new `event_id`** (for example `-r2`) so the idempotency key is fresh; a reused id just returns the old receipt.
3. **Verify.** `POST /lesson {op:get|list, source:wiki, topic:<topic>}`. Require `source:"wiki"` in the reply — a door that ignores `source` is stale and must fail loudly. Record the page id, revision, slug and next review date.
4. **Record.** Append a DONE line with event id, revision and verification result to `docs/ssot/jobs/education/<job>.yml`; commit and push. Put card ids in `where_filed` so a later session can find the evidence.
5. **Re-check after merge** if the source files lived on an unmerged branch: the education-report drift checker reads the idc03 checkout, so paths not yet merged show `source-gone`. Pull, re-run `EDU_SOURCE=wiki python3 scripts/education-report.py`, and close the recheck card only when the flags clear.

## Guardrails

- No direct MediaWiki API calls, no stored wiki credentials — the door owns login, idempotency and the outbox; failed writes queue there, not in the caller.
- `Education:` is Lockdown-protected and `private`; keep personal/private material out of the public `wiki` / `News:` surface. Use `wiki-private` / `PrivateNews:` when a write must be hidden.
- Pointer-first: SSOT keeps a verdict row and `ref:`/`see:` pointers; prose belongs in `docs/kb` and wiki lessons.
- Back up any template before editing it (`/wiki/page` allows `แม่แบบ:Education` and `แม่แบบ:Report`). A planned Cargo declaration was reverted because table creation needs host-level maintenance — do not half-configure the template.
- Be concise in the reply: page title, revision, receipt status and where filed are enough.

## Reference

- `scripts/skills-wiki-export.py` — offline renderer and skill inventory.
- `docs/kb/ada-ocb-skills-education.md` — pointer-first write-up.
- `docs/ssot/jobs/education/2026-11-24-skills-wiki-education.yml` — job trail with receipts and verify steps.
- `docs/kb/board-api-write-door.md` — `/publish` event shape and sink contract.
