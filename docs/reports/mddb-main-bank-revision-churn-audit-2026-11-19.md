# MDDB main-bank revision churn audit — 2026-11-19

Read-only audit of the four main-bank collections flagged after the
2026-11-19 compaction window (same-day ENOSPC incident: `mddb-backup`
streaming a ~19 GB mddb-ops snapshot filled idc03's disk —
`docs/ssot/jobs/board/2026-11-19-torn-card-write-enospc.yml`). Follow-up
to completed card `mddb-storage-reduction-retention-relocation`
(MEM-0871) — scope is the *remaining main-bank churn only*.

Target: `ada-ha-bank-home`, `ada-ha-bank-general`, `ada-ha-bank-devin-tony`,
`ada-ha-bank-devin-handoff` on the idc03 leader (`:11023`, db `/app/data/mddb.db`,
2.75 GiB, mode `wr`, mddbd 2.18.10). Method: live `GET /v1/stats`,
`GET /v1/collection-config`, `POST /v1/search` (enumeration, no content),
`POST /v1/revisions` per doc (timestamps + meta diff). No writes, no
config changes, no embedding/model calls. Per-doc census data:
`docs/reports/mddb-main-bank-revision-churn-audit-2026-11-19/*-census.json`
(key, written_by, rev count, first/last rev timestamp for all 10,979 docs).

## Live counts vs maxRevisions (2026-11-19 ~14:40 ICT)

| collection | docs | revisions | rev/doc | maxRevisions live |
|---|---:|---:|---:|---|
| ada-ha-bank-home | 34 | 21,696 | 638 | **none** (`configured:false`) |
| ada-ha-bank-general | 365 | 20,978 | 57 | **none** |
| ada-ha-bank-devin-tony | 2,877 | 38,790 | 13.5 | **20** (the only in-scope guard) |
| ada-ha-bank-devin-handoff | 7,703 | 21,487 | 2.8 | **none** |

Guard coverage across the whole main bank is spotty — only 6 of ~35
collections have `maxRevisions`: `ada-ha-bank-devin-tony`=20,
`ada-ha-events-tony`=20, `ada-ha-events-michael`=20,
`ada-ha-scenario-reports`=20, `ada-cms-pages`=50, `yomi-digest`=20.
The 2026-10-26 policy statement ("main bank x6 colls=20", prior card
comms) does not match live state — whether a subset was never applied or
was lost during later maintenance is undetermined, but **today 3 of the 4
in-scope collections are unbounded**, as are every other revision-heavy
bank (`projects-tony` 19,028 revs/162 docs, `github` 6,740/79,
`device-telemetry` 20,265/3,567, `people` 5,962/77, `purchase` 4,460/48,
`personal-kk` 4,033/106, `personal-tony` 4,509/192, `ideas-tony` 2,670/38,
`note-tony` 2,705/42, `personal-testo` 275/1 — all `configured:false`).

## Root cause — three churn machines, all heartbeat/duplicate writes

Stored revisions hold **timestamp + meta only** (no contentMd observed in
any sampled revision), so every writer below burns a revision row +
meta-index entries without preserving new content.

### A. `list_docs` pagination bug → hourly mass re-add (biggest ongoing churn)

`Mddb.list_docs()` in `scripts/ada/sync-ada-memory-to-mddb.py:178` calls
`POST /v1/search {collection, limit: 5000}` — but **the server caps page
size at 1,000** (verified live: `limit:5000` on devin-tony returns exactly
1,000, key-sorted `devin-session/*` … `devin/33*`). Every doc past the
first 1,000 is absent from the remote map → `old is None` → unconditional
`add` on every run.

- **Producer:** `devin-summaries-sync.timer` on tony-omen (`*:45`,
  `sync-devin-summaries.py --enrich`, ssot.jobs.yml `devin-summaries-sync`)
  plus per-host companion units (`systemd/devin-summaries-sync.timer`,
  also `*:45`) and `ada-memory-pull.service` (`*:30`, tony-omen, runs the
  same script).
- **Proof:** of the 1,323 devin-tony docs with a revision in the last 24 h,
  **1,321 are invisible to `list_docs`**; sampled `devin/3376ade05c4b4149`
  shows identical-meta rewrites at 09:45, 10:45, 11:45, 12:45. Top docs
  (`devin/75f6d91d8fe843c0` = 197 revs etc.) show 102 of 197 writes at
  minute `:45`.
- **Rate:** ~1,321 re-adds/hour ≈ **~31.7k writes/day**, each also
  queuing an embed call. This alone explains devin-tony's 38,790 revs.
- Same defect is latent in the vault sync for any collection >1,000 docs;
  in devin-handoff the vault-managed keys (`extract-*`, `devin-handoff/*`)
  happen to sort inside the first 1,000, so the vault-sync half of the bug
  isn't firing there *today* — but any future vault key sorting past
  position 1,000 gets hourly-recreated.

### B. `record_use_bg` use-tracking → one revision per recall hit

`memory_ops.record_use_bg` (ada-voice, landed 2026-09-21 —
`ssot.apps.ada-memory-progress.yml`) re-adds a doc on every
`ada_memory_search`/bank-recall hit to bump `use_count`/`last_used`.
Fire-and-forget, no debounce.

- **Proof:** in every high-rev vault doc examined, `use_count` is the
  meta key that changes between ~94–99% of consecutive revisions
  (access-procedure 839/893, google-tasks 530/533, handoff
  extract-bfb1099877-1 770/783).
- **Extreme case:** the five `note/flood-*` docs in ada-ha-bank-home hold
  17,984 of 21,696 revisions (83%) — 3,174–3,727 each — bursting 300–500
  writes/day during the Oct 1–12 flood window (median inter-revision gap
  **44 s**), sparse since (last touch 11-19 13:15). 3,723 stored revs of
  one doc share byte-identical content; only `last_used` differs, and
  only 26 times.
- It also writes on **read-only banks** (devin-tony is `writable:false`;
  `devin/75f6d91d8fe843c0` still shows 154 `use_count` bumps) — write
  policy gates tools, not the tracker.

### C. `ada-memory-sync` hourly ping-pong + forced daily rewrite

`ada-memory-sync.timer` (vault↔MDDB sync, idc03/mn01) writes whenever
`_managed_meta(remote)` ≠ `build_meta(frontmatter)`:

- `use_count`/`last_used` **are in `MANAGED_FIELDS`** (schema
  `ssot.apps.ada-memory-schema.yml`) but are never vault-declared → once
  B touches a doc, the sync sees it as permanently dirty and rewrites it
  hourly, dropping the counters; B re-adds them next recall → ping-pong.
  195/534 consecutive revisions of `general/google-tasks` are
  `use_count`-drop writes, **192 of them at exactly minute `:00`**.
- `build_meta` stamps `valid_from`/`last_verified` with **today** when
  frontmatter lacks them → every vault doc without those fm fields is
  rewritten once/day at the first post-midnight run (access-procedure:
  consecutive `00:00` writes 11-08 → 11-18, `valid_from` changed 50×).
- Live cadence is still **hourly at `:00`** (writes 11-19 01:00, 14:00) —
  the repo unit moved to `:17` on 11-18 (`7d3196d2`) but the installed
  unit on the writer host hasn't taken it.

## Per-collection findings

### ada-ha-bank-home — 34 docs / 21,696 revs · heartbeat-dominated

| revs | key | writer | span |
|---:|---|---|---|
| 3,727 | note/flood-banbueng-chonburi (en) | ada+console (research) + use-tracker | 09-30 → 11-19 |
| 3,725 | note/flood-rama9-bangkok (en) | same | 09-30 → 11-19 |
| 3,723 | note/flood-rayong-suanson (en) | same | 09-30 → 11-19 |
| 3,635 | note/flood-chonburi-province (en) | same | 09-30 → 11-19 |
| 3,174 | note/flood-tow-trucks-samutprakan (en) | console + use-tracker | 09-30 → 11-19 |
| 920/900/894/891 | ada-layout / home-topology / access-procedure / tv-casting | obsidian-vault + ping-pong | 09-30 → 11-19 |

Everything else is trivial (extract-* drafts ≤11 revs; th-lang flood
mirrors and `tv-power-control` have zero stored revs). **~99% of this
collection's history is duplicate/heartbeat writes** — the flood notes
were recalled constantly while Tony asked Ada about the October floods;
the vault docs churn via B+C.

### ada-ha-bank-general — 365 docs / 20,978 revs · heartbeat-dominated

- `obsidian-vault`-stamped docs: 107 docs, **17,620 revs (84%)** —
  ping-pong churn; top `extract-2026-09-23-e63dd32b04-0` 564,
  `general/google-tasks` 534, `standard-workflow-ada-drafts…` 480.
- `conversation_memory` extract drafts: 198 docs, 2,396 revs (normal).
- `ada_remember` 479 · `devin-cli` 370 (`yomi-vs-line-bot`, heavily
  recalled) · `devin` 103 · `nest-io` 10.
- Churn is currently quiet (only 18 docs revised <7 d) — dormant, not
  fixed; it resumes the moment those docs are recalled again.

### ada-ha-bank-devin-tony — 2,877 docs / 38,790 revs · writer bug-dominated

- `devin-cli` `devin/<hex>` docs: 2,050 docs, **37,882 revs (97.7%)** —
  dominated by the `list_docs` hourly mass re-add (A), plus use-tracker
  bumps (B) on the ~1,000 visible docs.
- 1,396 docs sit at the 20-rev cap (1,300 of them touched <7 d — the cap
  is doing its job *for written docs*); 94 docs carry >20 revs (up to
  197) — pre-guard residue that will trim on their next write.
- `devin-desktop` `devin-session/*`: 574 docs / 693 revs — expected
  (summaries update while a session lives, then stabilize).
- `devin-dispatch` 233/189, `distill-devin-bank` 9/17 (weekly rollup +
  supersede), `gh-radar` 8/9 — all expected history.
- **This is the only collection where the churn is large AND growing
  today** — ~31.7k heartbeat writes/day from bug A alone.
- Minor secondary writer: 57 of `devin/75f6d91d`'s writes land at `:00`
  — consistent with a second sync instance (per-host companions or
  `ada-memory-pull` on tony-omen); same bug, different host.

### ada-ha-bank-devin-handoff — 7,703 docs / 21,487 revs · mixed

- **19 obsidian-vault docs hold 11,803 revs (55%)** — `extract-2026-09-23-*`
  + `devin-handoff/*` canonicals, ~620–780 each, ping-pong B+C,
  churned 09-30 → 11-06 then dormant.
- **8 ada_remember `devin-handoff/*` docs: 1,116 revs** (up to 331 each) —
  same ping-pong window, dormant since 11-06.
- `dispatch-close-out`: 6,188 docs / 6,948 revs (**~1.12/doc**, 92% at
  1 rev) — expected write-once outcome banking.
- `devin-dispatch`: 1,366 / 1,527 — expected handoff/job spec updates.
- 6,703 docs are invisible to `list_docs` (>1,000 cap) but they're
  producer-owned (close-out/dispatch), not vault-managed — the
  invisibility bug isn't burning them today; it *is* a latent hazard if
  vault-backed keys ever sort past position 1,000.

## Expected history vs duplicate/heartbeat

| class | share of in-scope revs |
|---|---|
| **Duplicate/heartbeat** (A mass re-adds + B use-count bumps + C ping-pong/daily-rollover) | ~85–90% — essentially all of home (99%), general (84%), devin-tony (~98%), and the handoff vault/remember docs (~57% of handoff) |
| **Expected update history** | handoff close-out/dispatch docs (~43% of handoff), devin-session summaries while live, extract drafts, weekly distill supersedes |

## Recommendations

Priority order — the writer fixes matter more than the guard, because the
guard only trims what the bugs keep regenerating.

1. **Fix `list_docs` pagination** (`scripts/ada/sync-ada-memory-to-mddb.py:178`):
   page `POST /v1/search` with `offset` until a short page returns (server
   caps at 1,000/page). One-line comment in the file already says
   "revisit paging if any bank grows past it" — that day arrived at
   >1,000. Kills ~31.7k writes+embeds/day on devin-tony and the latent
   vault-sync re-add bug on any >1,000-doc collection.
2. **Debounce `record_use_bg`** (ada-voice): write at most once/doc/day
   (only when `last_used` actually rolls), or drop the counter bump when
   the doc is unchanged — today every recall hit is a stored revision.
   Optionally confirm whether `PATCH /v1/update` (meta-only, used by
   `distill-devin-bank.py:update_meta`) stores revisions — if not, it's a
   drop-in fix.
3. **Exclude use-tracking fields from the sync dirty-check**
   (`sync-ada-memory-to-mddb.py`): `use_count`/`last_used` (and
   `outcome*`) are remote-computed, not vault-managed — drop them from
   `MANAGED_FIELDS` for the comparison so touched docs stop looking dirty.
4. **Stop stamping `today` into `valid_from`/`last_verified`** in
   `build_meta` when frontmatter lacks the field — preserves remote value
   and kills the forced daily 00:00 rewrite.
5. **Apply maxRevisions per the declared main-bank policy (=20, or
   tighter below) then `/v1/truncate`** — recommend:
   - `ada-ha-bank-home`: **10** (canonicals + notes; all history is meta-noise)
   - `ada-ha-bank-general`: **10**
   - `ada-ha-bank-devin-handoff`: **10** (close-out docs are ~1 rev)
   - `ada-ha-bank-devin-tony`: keep **20** (already set; session docs are
     the only ones whose revision history has residual value)
   - extend to the other unbounded churners in the same pass:
     `projects-tony`, `github`, `people`, `purchase`, `ideas-tony`,
     `note-tony`, `personal-*`, `device-telemetry`, `ada-ha-events-kk`,
     `ada-ha-events-dev`, `ada-ha-recall-summary-*`, `ada-ha-actions-*`,
     `ada-ha-snapshots-*`, `host-logs-state`, `ada-ha-nlm-answers-*`,
     `ada-ha-bank-developer-tony`, `ada-ha-bank-dev-scratch`.
6. After the writer fixes land, a periodic `/v1/truncate`+ offline bbolt
   compact (precedent: `docs/kb/mddb-prune-compact.md`) reclaims the
   freelist these ~84k churn revisions keep feeding.

## Evidence index

- Live stats: `get_stats` (MCP→leader :11023) — 28,211 docs / 188,609 revs / 2.75 GiB.
- Config: `GET /v1/collection-config?collection=<c>` for all 35 collections.
- Per-doc census: `*-census.json` beside this report (key, lang, addedAt,
  updatedAt, written_by, source, kind, status, rev count, first/last rev
  timestamps) — 34 + 365 + 2,877 + 7,703 docs; totals reconcile exactly
  with `/v1/stats` revision_count.
- Revision meta-diff samples: `note/flood-rayong-suanson` (3,723 revs,
  only `last_used` varies), `access-procedure` (894 revs, `use_count`
  839×, `valid_from` 50×), `general/google-tasks` (534 revs, 192 drops at
  minute `:00`), `devin/3376ade05c4b4149` (identical-meta writes at
  :45 hourly), `extract-2026-09-23-bfb1099877-1` (784 revs, `use_count` 770×).
- `list_docs` cap proof: `POST /v1/search {limit:5000}` → exactly 1,000
  docs; 1,321/1,323 docs revised <24 h are outside that window.
- Producers: `systemd/devin-summaries-sync.timer` (`*:45`, per-host),
  `systemd/ada-memory-pull.timer` (`*:30`, tony-omen),
  `systemd/ada-memory-sync.timer` (`*:17` repo / `:00` live, idc03+mn01),
  `memory_ops.record_use_bg` (ada-voice),
  `systemd/devin-bank-distill.service` (Sun 10:15, con01).
