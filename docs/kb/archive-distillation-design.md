# Archive distillation — design (DRAFT for review)

Status: proposal, 2026-09-23. Supersedes "extract a few docs then archive".

## Goal

When a repo goes stale (chaba0, ada, future archives), don't keep its raw
outdated docs — **distill into topic-organized archive reports** stored in
chaba's unified memory, verify coverage, then archive the repo on GitHub.

Principle: *organized memory over raw history*. Git history stays on
GitHub (archived, retrievable) — the knowledge lives in the banks.

## Pipeline

```
source repo
  → inventory (file manifest + sha256 per file)
  → topic map (proposed clusters, human-reviewed)
  → per-topic archive report (schema below)
  → coverage audit (every input file accounted for)
  → sync to chaba-archive bank (read-only)
  → archive repo on GitHub
```

## 1. Inventory + coverage manifest

`docs/archive/manifests/<repo>.yml` — the audit backbone:

```yaml
repo: chaba0
commit: <head sha at distillation>
files:
  - path: docs/pc1-runbook.md
    sha256: ...
    size: 3736
    topic: host-operations        # which report consumed it
    # or: topic: excluded-noise   # vendored/changelog/binary
  - path: mcp/mcp-playwright/modules.old/**/*
    topic: excluded-noise         # must still be LISTED
audit:
  total_files: 2228
  covered: 31          # files distilled into reports
  excluded: 2197       # declared noise
  unaccounted: 0       # MUST be 0 — the audit gate
```

Rule: **every file in the source tree appears exactly once** — either
consumed by a topic report or declared noise. `unaccounted: 0` is the
gate; anything left over fails the archive step.

## 2. Topic map (reviewed before extraction)

Proposal doc per repo, e.g. chaba0:

| Topic | Source files | Disposition |
|---|---|---|
| host-operations | pc1-runbook, host-*.json, stacks-*.json | distill → note which hosts map to current names |
| network-topology | dns/zones, *url*.json, vpn.db | historical facts only |
| reorg-methodology | *reorganization-patterns.md | rewrite for current hosts — still true |
| docker-practices | docker-management.md | merge into chaba kb if non-duplicate |
| deployment-procedures | line-webhook-deployment, mcp-nodehost | superseded by deploy-ada.sh — note only |

Topics are approved before extraction — that's the review gate.

## 3. Archive report schema

`docs/kb/archive/<repo>/<topic>.md`:

```markdown
---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: <sha>
topic: host-operations
status: historical        # historical | partial-current | superseded
period: [2025-10, 2026-02]   # when this topic was live knowledge
follows: []                 # what it replaced (older repo/report)
superseded_by: idc01-stack  # what replaced it (newer report/current doc)
covers: [docs/pc1-runbook.md, docs/host-pc1.json, ...]
extracted: 2026-09-23
---

# <Topic> — archive of chaba0

## Summary          (what this topic was about)
## Timeline         (dated events: how the topic evolved — see §5a)
## Still-true facts (verified against current state — each tagged
                      [still-true] / [historical] / [superseded-by X])
## Key details      (the actual distilled content)
## Source map       (source file → which section covered it — audit trail)
## Not preserved    (explicitly-declared drops: "pc1 IP addresses — host retired")
```

The `Not preserved` section is the honesty mechanism — extraction loss
must be *declared*, not silent.

## 3a. Timeline — the time-domain view

Two levels:

**Per-report `## Timeline`** — dated events mined from source docs +
git history (`git log --format=%ad -- <file>` gives real dates, better
than guessing):

```markdown
## Timeline
- 2025-10-12: pc1 stack plan drafted (docs/system-inventory/pc2/stack-plan.md, commit a1b2c3)
- 2025-12-06: pc2 inventory snapshot — first full census
- 2026-01-15: vpn mesh rewired to idc1 (docs/idc1-vpn.json)
- 2026-02-02: topic frozen — project moved to chaba
```

**Global `docs/kb/archive/TIMELINE.md`** — generated from all reports'
timeline sections + `period` fields, sorted by date:

```
2025-10 ├─ chaba0: host-operations begins ─┐
2025-12 ├─ chaba0: network-topology ─┐     │
2026-02 ├─ chaba0 archived ──────────┼─────┘
2026-09 └─ chaba: unified memory ◄───┘  ← links: supersedes/superseded_by
```

Cross-links (`follows`/`superseded_by`) make the chain machine-
traversable: Ada can walk "pc1-era → idc01-era" as a narrative.
The audit verifies every timeline entry has a source ref + parseable
date, and that link targets exist.

## 3b. SSOT persistence — so the convention isn't lost

The schema lives in SSOT, not just this doc:

- **`docs/ssot/apps/ssot.apps.ada-memory-banks.yml`** — register
  `chaba-archive` as a read-only bank (same policy block as
  `devin-kb`/`chaba-docs`: `writable: false`, `source: sync-docs`).
- **`docs/ssot/apps/ssot.apps.archive-distillation.yml`** (new) — the
  canonical schema: front-matter fields, manifest format, audit rules,
  timeline format, status vocabulary, `Not preserved` requirement.
  Future archive jobs validate against this file — that's how the idea
  survives session boundaries.
- **`docs/kb/archive/`** tree is the data; the SSOT file is the law.
- `scripts/sync-docs-to-mddb.py` source map gains `chaba-archive` →
  `docs/kb/archive/` so reports index like any other bank content.

## 4. Coverage audit

`scripts/audit-archive.py` (new):

1. Parse manifest → assert `unaccounted == 0`.
2. For each report: parse `covers:` → every listed file exists in
   manifest with matching sha256.
3. Per-file check: its declared topic matches a report that lists it.
4. Optional residual pass: for each source file, emit a one-line
   "what was kept" diff summary for human spot-review.
5. Output: coverage %, declared-loss list, PASS/FAIL.

Human gate: review the `Not preserved` sections + the topic map —
machine guarantees completeness of *accounting*, human verifies
quality of *extraction*.

## 5. Ada / SSOT integration

- **DECIDED**: dedicated read-only bank `chaba-archive` — stale content
  never contaminates `chaba-docs` recall; Ada opts in deliberately via
  `kind=archive-report` / `source_repo` / `topic` / `status` meta.
- Meta tags Ada can query dynamically: `kind=archive-report`,
  `source_repo`, `topic`, `status` — same filter_meta contract as
  `status: active` on writable banks. "Dynamic SSOT" = the metadata IS
  the query surface.
- An `INDEX.md` archive-report lists all topics per repo — Ada can
  discover "what exists about X from the old projects" in one hit.
- Superseded facts are tagged in-line so Ada answers "that was the OLD
  pc1 — current equivalent is tony-dell" correctly instead of quoting
  dead IPs.

## 6. Why reports > raw dumps

- A raw 150KB docs/ tree embedded verbatim = stale IPs/hostnames
  scoring high on similarity → actively wrong recall.
- Topic reports keep **facts that outlived the topology** (methodology,
  decisions, "why" context) and declare drops explicitly.
- Reports are re-distillable later — the manifest pins source sha.

## 7. Execution plan (chaba0 first, then ada)

1. Write `ssot.apps.archive-distillation.yml` (schema = law) + register
   `chaba-archive` bank + source map in `sync-docs-to-mddb.py`.
2. Inventory + manifest for chaba0 (script-assisted).
3. Topic map → your review.
4. **Extraction benchmark** (see §8) — split topics Devin vs Gemini.
5. `audit-archive.py` → coverage 100% / declared-loss review.
6. `sync-docs-to-mddb.py` → `chaba-archive` bank.
7. Canary addition: 1-2 known-answer questions against archive topics.
8. `gh repo archive tonezzz/chaba0` (+ ada, chaba_weaviate after same
   treatment).

## 8. Extraction benchmark — Devin vs Gemini/Ada

Same corpus, same topic map, different writers — measure who distills
better:

- **Split**: Devin takes `host-operations` + `network-topology`
  (structured/JSON-heavy); Gemini (via the ada-pi summarizer or direct
  API on the same sources) takes `reorg-methodology` +
  `docker-practices` + `deployment-procedures` (prose-heavy).
- **Rubric** (per report):
  - coverage: % of assigned files consumed (audit-checkable)
  - fact retention: N still-true facts vs a ground-truth list we
    pre-write per topic ("the 5 facts that MUST survive")
  - declared-loss quality: does `Not preserved` catch the real drops?
  - factual errors: spot-check samples
  - time + cost (tokens/$)
- Output: scorecard in the manifest's audit block → decision on which
  engine runs future archives (or hybrid: Gemini drafts, Devin audits).

## Decisions (locked)

- Bank: dedicated `chaba-archive`.
- Path: `docs/kb/archive/<repo>/<topic>.md`.
- Extraction: benchmark Devin vs Gemini/Ada before committing to either.
