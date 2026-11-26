# Dispatch outcome — MediaWiki Infrastructure/Hosts hierarchy (SYS-1034)

## What changed

- **`scripts/wiki-infra-hosts.py` (new)** — renders the canonical MediaWiki
  hierarchy: `Infrastructure:Hosts` rollup + `Infrastructure:Hosts/<host>`
  leaves. Host set is derived from `ssot.audit.hosts.yml` `hosts:` (10
  declared hosts) — no hardcoded list. Sources: latest
  `reports/audit-hosts/<host>-*.yml` + `meta.<host>.yml`,
  `reports/host-loads/host-loads.yml`, `reports/disk-trend/disk-trend.yml`,
  MDDB `ada-cms-pages` `timer-timeline[-<host>]` docs (best-effort `/get`),
  `ssot.reports.yml` node registry (related-report links), and
  `host-services-cms.py` `HOST_META` (compatibility links, imported not
  copied). Leaf carries report_role=leaf, parent, status
  (active|degraded|unreachable|retired), role, last_verified, services,
  capacity/load/disk, expected-service delta, sources, related reports,
  compatibility. Rollup carries report_role=rollup, one row per declared
  host (status/freshness/role/key warning/link), children, watch list.
- **`scripts/ada/host-services-cms.py`** — HOST_META reconciled to the
  registry: added con01, macbook, kk-mac; idc01 is now a retired stub
  (not probed); stale "six leaf pages" docstring fixed.
- **`docs/ssot/infrastructure/ssot.reports.yml`** — registered missing
  `audit-hosts/idc02` and `audit-hosts/con01` L1 nodes and added both to
  `fleet.children` (audit-hosts.py audited them; the registry never
  declared them).
- **`ssot.automation.yml` / `ssot.audit.hosts.yml`** — "6 leaf pages"
  notes updated to registry-driven wording.
- **`docs/ssot/jobs/infrastructure/2026-11-24-mediawiki-infra-hosts-hierarchy.yml`**
  — runbook + page contract + privacy model + verification record.

## Privacy gates

- `--apply` publishes via board-api `/wiki/page` (Infrastructure: prefix
  already allowlisted) only after an anonymous api.php probe confirms
  `Infrastructure:Hosts` content read is denied — verified live:
  `accessdenied`. `--private-ok` overrides for pre-verified runs.
- `--surface public` renders a sanitized fleet-status derivative
  (host/status/freshness only) to files; `public_scrub()` fails on any
  port/route/IP/unit-name leak (timestamps and CSS are masked first).
  No public publish path exists — `/wiki/page` refuses other namespaces.

## Verification (all in this worktree, mn01)

- `python3 scripts/audit-hosts.py --host <h>` ×6 + `host-loads.py`
  (6/9 sampled) produced real report data; `--out-dir` dry-run wrote 11
  pages. Rollup: 6 degraded (real deltas), 3 unreachable
  (con01/kk-mac/michael-ha — not reachable from mn01), 1 retired (idc01).
- `--check` exit 0 (private and public surfaces); `--host idc03 --check`
  exit 0; missing/orphan/required-field/compat-link gates all pass.
- `host-services-cms.py --slug services-idc01 --dry-run` renders the
  retired stub without probing.
- SSOT validation passed on commit (pre-commit hook).

## Not done / next step

- **Pages were NOT published.** mn01 cannot reach con01/kk-mac/
  michael-ha, so pages built here would stamp false `unreachable` rows.
  Run `python3 scripts/wiki-infra-hosts.py --apply` on tony-dell (broadest
  reachability, freshest reports/) — see the job doc runbook.
- No timer wired yet; a weekly timer beside `chaba-services-regen` on
  tony-dell is the natural follow-up.

lessons:
- MediaWiki wikitext needs `[[Title|text]]` links — markdown `[t](url)` does not render; the /wiki/page door only accepts Education:/Reports:/Infrastructure: (+templates) titles.
- PUBLIC scrub regexes must mask ISO timestamps/`HH:MM` before matching `:\d+` ports, and strip `style="..."` (`font-size:90%` false-positives).
- audit-hosts.py FAILED_NOISE + SSOT known_failed must be applied to raw failed-unit lists or desktop flakiness (e.g. grub-initrd-fallback) degrades hosts.
- ssot.audit.hosts.yml `hosts:` is the real fleet registry (10 hosts incl. retired idc01, member kk-mac, HAOS michael-ha) — audit-hosts.py HOSTS and host-services-cms HOST_META were both stale subsets.
- reports/* is gitignored — dry-run data only exists on producer hosts; dispatch worktrees must run the collectors (audit-hosts/host-loads) locally or accept "no live data" leaves.
