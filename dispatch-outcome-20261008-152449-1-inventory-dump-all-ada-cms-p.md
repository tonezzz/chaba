# cms-ia-reorg — CMS information architecture for ada-cms-pages

## What changed / was found

**Inventory** (`reports/cms-ia-inventory-2026-10-08.md`, in worktree —
`reports/` is gitignored by repo convention): live MDDB dump showed 389
docs / 280 keys / 110 th variants. Real clusters (by actual use, not
aspiration): cctv/cameras ~98 keys, research/notes ~47, domain digests
~24, ops/infra ~22, news/flood/media ~18, bench ~21, personal ~18,
meta/test ~6. **No exact duplicate key+lang pairs ever existed** — the
"dups" were near-duplicate keys and superseded pages being revived by
their generator.

**Dedup** — resolved via supersede/redirect (content kept as history;
every `superseded_by` target verified live+active):
- `cam-dohweb-{vibhavadi,min-buri-hwy304,bang-pu-sukhumvit,
  hwy303-phra-samut-chedi}` → `cam-traffic-doh-*` twins (same PER_* DOH
  streams). Root cause fixed in `scripts/cam-wall/zones.yml` — the 4
  Bangkok cams removed from `dohweb.cams`, which is why cam-wall-cms
  kept republishing the superseded pages.
- `infrastructure-digest`→`infra-digest`, `uncategorized-digest`→
  `reports-index`, `services-by-host-2026-09-30`→`services-by-host`,
  `gold-report`→`gold-price-report`.
- Kept as genuinely distinct: `transcript-audit-2026-09-28|29` (dated
  session snapshots), `nut-summary`/`nut-benefits-summary`.

**Meta normalization** — `scripts/ada/cms-ia-normalize.py` (new, idempotent,
dry-run default): applied twice to live MDDB (145+184 docs). Result:
every doc now has `kind`, `domain`, `status`; `benchmark`→`report`,
`infrastructure`→`infra`, `published`→`active`; `page_role`
(wall/cam/index) backfilled on all 85 camera pages.

**Standard** — `docs/ssot/infrastructure/ssot.cms.yml` (new, passes
ssot-validate-all): kind/status/domain enums, slug prefix families
(cam-*, bench-*, status-*, note-*, report-*, *-digest…), nav
domain→section map, supersede-based dedup + lifecycle rules, producer
contract.

**Grouped reports-index** — `scripts/lib/cms_index.py` renders
`reports-index` grouped into the 12 nav sections (digests, reports,
cameras, flood, news, bench, ops, research, projects, personal, docs,
meta); `report-distill.py` now delegates to that shared renderer;
ada-pi `tool_runner/cms.py::_cms_reports_index` mirrors it. The live
`reports-index` was regenerated — verified grouped output.

**Viewer** — ada-pi `pwa/cms/index.html` (branch `cms-ia-reorg`, commit
37547a5, in `ada-pi-wt/` worktree — **committed, not pushed, not
deployed**): all slug/title heuristics replaced by `pageSection()` /
`tabScope()` driven by meta kind/domain/report_role/zone_tab/page_role.
`?tab=security|traffic|flood` still works for the HA dashboard iframes;
unknown future domains auto-render as their own section.

**Producers** — cam-wall-cms (stamps `page_role`, docstring →
ssot.cms.yml), bench-edge-cms, kanban-cms, ada-pi `cms_publish_page`
all reference the standard in their docstrings/help.

## Result

All acceptance criteria met except the viewer change needs merge+deploy
in ada-pi (out of scope for dispatch — no push/deploy authorized). Zero
duplicate keys, every page tagged kind+domain+status, standard committed
to SSOT, reports-index grouped and live.

## How to verify

- `python3 scripts/ada/cms-ia-normalize.py` — dry-run should print
  "0 docs planned" (idempotent).
- `GET ada-cms-pages/reports-index` — section headers per nav group.
- `node scripts/ssot-validate-all.mjs` — ssot.cms.yml ✅ (2 pre-existing
  failures in unrelated job ymls).
- Viewer: merge ada-pi `cms-ia-reorg` branch, deploy via
  `deploy-ada.sh`, open `/apps/ha/ada-tony/cms/` — sidebar groups by
  section; `?tab=traffic` still scopes to traffic cams.
- JS grouping logic smoke-tested under node (all asserts pass); python
  files py_compile clean.
