# Dispatch outcome — docs-map one registry across all doc stores

Card: docs-map-one-registry-across-all-doc-sto-7ac35a (OPS-1184)
Host: idc02 dispatch worktree, branch dispatch/20261121-190814-produce-docs-ssot-infrastructu

## What changed

- **docs/ssot/infrastructure/ssot.docs-map.yml** (new) — the registry.
  One entry per named store: repo-kb (docs/kb ~440 files), repo-ssot
  (docs/ssot tree), repo-reports (docs/reports ~34), gdrive-ada-nest
  (queue/packs/projects/datasets/reports/archive + folded lanes), mddb
  (5 planes with live-measured collection census), wiki (News/,
  PrivateNews:3002, Infrastructure:3000, Education:3004, Reports:3006),
  wp (member surface + frozen lesson archive + ledgers + news feed).
  Each store records owner, canonical path/prefix/URI pattern, content
  types, write/update path, authority/volatility, concrete lookup
  recipe, and notes/gaps. A `doc_types:` map (14 types) resolves each
  doc type to its canonical store — the actual "where does X live"
  answer. Cross-references Wiki:Wiki-Hierarchy (the live wiki page this
  pattern extends) plus the per-store standards files.
- **scripts/ssot-docs-map-check.py** (new) — check entrypoint:
  `python3 scripts/ssot-docs-map-check.py` verifies the 7 stores, all
  required fields, non-empty lookup recipes, and doc_types→store
  resolution; `--live` adds read-only HTTP probes of the MDDB planes,
  wiki api.php, and WP origin REST.
- **docs/ssot/ssot.index.yml** — registered under "System &
  Environment" (both mirrored sections, matching the file's own
  duplicate-entry pattern) next to ssot.storage.yml.
- **docs/ssot/CHANGELOG.md** — minor entry for 2026-11-21.
- **docs/ssot/jobs/infrastructure/2026-11-21-docs-map-registry.yml** —
  job record with verified facts + follow-ups.

## Verified

- `ssot-docs-map-check.py` — 0 errors: all 7 stores present, all fields,
  all 14 doc_types resolve.
- `ssot-docs-map-check.py --live` — all 7 endpoint probes HTTP 200 from
  idc02 (mddb :11023/:11027/:11026 on idc03, :11025 + :11023 follower on
  idc02, wiki api.php, wp origin REST root).
- `node scripts/ssot-validate-all.mjs` — both new files ✅ Valid; the 5
  repo-wide errors are pre-existing focus-inbox/devnest files.
- `ssot-prose-smell.py --file` — 0 flagged scalars.
- MDDB plane facts measured live via /v1/stats, not copied from docs:
  cms :11027 = 19 collections (ada-cms-pages 1435, chaba-lessons 181,
  infrastructure-ssot 7596, kb-operations 279); leader :11023 banks;
  :11026 host-logs 430k; :11025 ada-ha telemetry.

## Notable findings recorded in the registry

- mddb leader moved idc01 → idc03; the mddb-ops-split.md header topology
  is stale vs live (docs-map records the live map).
- kb-* MDDB mirror coverage of docs/kb is unverified
  (mddb-coverage-audit card still open) — grep stays the trustworthy KB
  lookup.
- docs/reports/ vs repo-root reports/ name collision flagged as a gap.
- Stray ada-cms-pages doc on :11025 + device-telemetry on two planes —
  noted under mddb gaps.

## How to verify

```
python3 scripts/ssot-docs-map-check.py --live
grep -n 'docs-map' docs/ssot/ssot.index.yml
```

lessons:
- ssot.index.yml duplicates every infrastructure entry across two
  mirrored sections ("System & Environment" + "(continued)") — index
  additions must be inserted twice or the halves diverge.
- YAML: unquoted scalar values containing ": " (e.g. `owner: chaba repo
  (writer: ...)`) fail parse — quote them.
- MDDB plane truth differs from docs: mddb-ops-split.md says leader on
  idc01, live is idc03 :11023; always /v1/stats the planes before
  writing endpoint facts.
- The MCP `mddb` server's get_stats hits one plane only (leader) — it
  does not reflect the cms :11027 collection census; use curl per plane.
