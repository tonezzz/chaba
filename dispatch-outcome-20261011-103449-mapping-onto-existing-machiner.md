# Dispatch outcome — project-lifecycle-pipeline (mapping pass)

## What this run actually was

The card's SOP (`docs/ssot/infrastructure/ssot.project-lifecycle.yml`) had
already landed in an earlier same-day session and the card was closed.
This queued dispatch therefore ran as a **verify-and-complete pass**:
check each machinery claim in the SOP against the code, close what was
still missing. Several promises were aspirational — fixed in-repo.

## What changed (all inside the worktree, on the dispatch branch)

| File | Change |
|---|---|
| `docs/ssot/infrastructure/ssot.project-lifecycle.yml` | Reconciled the SOP with reality: `project:<slug>` is a `tags:` entry (orthogonal to the existing `program:` domain field); explicit DECISION — no stored `stage:` field on cards (stage is derived from comms evidence tags; a mutable field would drift); board_filter note; canonical template path; intake-router syntax. |
| `docs/ssot/templates/project-page.md` | NEW — fill-in CMS project template (slug `project-<slug>`), conforming to `docs/kb/cms-page-standard.md`: status line, Latest, meta block, Cards/Decisions/Next sections, provenance footer. |
| `docs/ssot/kanban/ssot.kanban.yml` | card_schema now documents `tags:` (with `project:<slug>`/`kanban-ux` conventions + board-api limits) and `program:` — both were live fields with zero schema coverage (150+ cards already carry `program:`). |
| `scripts/render-board2.py` | Filter haystack now includes `c.tags`; `project:`-tagged cards render a 📁 badge. `program` was already searchable. |
| `scripts/render-board.py` | Classic view: `data-text` now includes `program` + `tags` on card tiles and sidebar rows — tag filtering works there too. |
| `scripts/board/review-digest.py` | New `kanban-ux` section: open cards tagged `kanban-ux` are listed by id+column, so friction cards in backlog surface on the digest (was: invisible unless in review). Served by `chaba-review-digest.timer` on tony-dell — goes live on next merge→pull, no deploy needed. |
| `docs/ssot/infrastructure/ssot.home-assistant.dashboards.yml` | Sweep bonus: fixed a pre-existing hard YAML syntax error (`Source:` inside a plain multi-line scalar) — the file now parses. |
| `docs/ssot/jobs/kanban/2026-10-11-project-lifecycle-mapping.yml` | NEW — job trail: decisions, verification, unverified claims. |

## Gap-by-gap result

1. **Project container** — ✅ CMS page template exists (file), `project:<slug>`
   tag convention documented + orthogonal to `program:`, board filters now
   actually see tags (previously false in BOTH views).
2. **TG idea intake** — ⚠️ contract fully documented (intake_router: match →
   file with tag → unsure = backlog card + clickable-options request). The
   ada-pi instruction deploy claimed by the earlier session (commit a6bea13)
   is **unverifiable from this worktree** — spot-check on idc03:
   `git -C ~/CascadeProjects/ada-pi log --oneline -3` + send a test TG idea.
   If the deploy didn't land, gap 2 reopens.
3. **Roles** — ✅ documented in SOP (Ada steward / Devin build / nest runner).
4. **Card-UX loop** — ✅ `kanban-ux` tag convention + review-digest lane
   implemented.

## Verify

- `python3 -m py_compile` on all three edited scripts; `yaml.safe_load` on
  every edited/new SSOT file.
- `python3 scripts/render-board.py` + `render-board2.py` — both generate
  clean over the real 459-card set.
- `node scripts/ssot-validate-all.mjs` — 2009 files, **0 errors** (was 1,
  the dashboards.yml break).
- `scripts/board/review-digest.py` — runs; digest lists current review
  pile; kanban-ux section correctly absent (no such cards yet).

## Left open

- ada-pi steward/intake deploy (a6bea13) unverified — see gap 2 above.
- First live exercise: next TG idea should produce a `project:<slug>`-tagged
  card or a clickable-options request — that is the end-to-end proof.
