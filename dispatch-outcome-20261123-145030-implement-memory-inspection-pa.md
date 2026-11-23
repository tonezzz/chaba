# Dispatch outcome — memory-inspection pages (memory-inspect-pages / MEM-0745)

## What changed

Commit `df2f40c5c0` on `dispatch/20261123-145030-implement-memory-inspection-pa`:

- **`scripts/ada/bank-inspect.py`** (new) — per persona lane
  (`ssot.apps.ada-persona-lanes.yml` instances → `cms_collection`), dumps
  every `ada-ha-bank-*` collection visible to that lane's instance from
  the memory plane (`:11023 /search`) as a
  subject → attribute → kind/value + modified digest, and writes
  `memory-inspect` (index) + `memory-inspect-<bank>` (leaf) pages into
  THAT lane's CMS collection (`:11027 /add`). Lanes: tony→ada-cms-pages,
  kk→ada-cms-pages-kk, michael→ada-cms-pages-mn,
  kk-dev→ada-cms-pages-kk-dev. `instances_readonly` mounts resolve to
  the mapped prod collection and are flagged `ro`. Only `ada-ha-bank-*`
  collections are dumped (kb-*/ada-cms-* registry entries are CMS-plane,
  not memory banks). Secret-keyed entries (credential-word subject/attr,
  or live-secret-shaped values) render `*(redacted)*` at write time.
  Flags: `--dry-run`, `--lane`, `--bank`, `--memory-mddb`, `--cms-mddb`.
- **`apps/cms-render/server.py`** — `detect_kind` now returns
  `memory-inspect` for `memory-inspect*` keys; `ada-cms-pages-mn` and
  `ada-cms-pages-kk-dev` added to `COLLECTIONS` so per-lane pages resolve
  and appear on the index.
- **`apps/cms-render/templates/memory-inspect.html`** (new) — extends
  `report.html`; gives the kind its chip + `/k/memory-inspect` listing.
- **`docs/ssot/infrastructure/ssot.jobs.yml`** — new job `bank-inspect`:
  host `tony_dell`, daily `05:40`, persistent, 15m timeout,
  condition_path on the script. Units rendered to
  `systemd/generated/tony_dell/bank-inspect.{service,timer}`.
- **`docs/ssot/jobs/ada/2026-11-23-memory-inspect-pages.yml`** — job record.
- **`tests/ada/test_bank_inspect.py`** (new, 12 tests) — lane map, bank
  visibility incl. ro mounts, row extraction + status filter, secret
  redaction, page shape, CMS write routing over a fake transport.
  **`tests/ada/test_cms_render.py`** — added memory-inspect kind cases.

## Result

- Test suite: `tests/ada` 313 passed / 1 skipped; merge-gate set
  (tests/board smoke + ssot refs) 231 passed; `render-jobs.py --check`
  OK 117 jobs / 8 hosts.
- Live run wrote real snapshots: 15 pages in `ada-cms-pages`,
  8 in `-kk`, 5 in `-mn`, 9 in `-kk-dev` (2,338 tony-lane entries
  indexed; 2 entries redacted in `ada-ha-bank-devin-tony`).
- Secret scan of every published memory-inspect page: clean.
- Snapshot generation **on tony-dell** confirmed: script staged at
  `/tmp/bank-inspect-verify/` (docs → real checkout) ran
  `--lane tony --bank github` → `ada-cms-pages/memory-inspect-github`
  upsert ok.
- `https://cms.surf-thailand.com/p/memory-inspect` renders 200 (old
  service falls back to page.html until chaba-cms-render redeploys this
  branch, which also activates the mn/kk-dev collections and the
  memory-inspect template).

## How to verify

```
python3 -m pytest tests/ada/test_bank_inspect.py tests/ada/test_cms_render.py -x -q
python3 scripts/ada/bank-inspect.py --dry-run --lane kk    # pages only
curl -s https://idc03.taila0626a.ts.net:8010/p/memory-inspect  # live page
```

After merge: on tony-dell `render-jobs.py --host tony_dell --ids
bank-inspect --install` (or wait for the jobs install path), then
`systemctl --user start bank-inspect.service` for the first scheduled
run, and redeploy `chaba-cms-render.service` on idc03 for the new
kind/collections.

## Notes / follow-ups

- `personal` + `personal-tony` banks both resolve to
  `ada-ha-bank-personal-tony` for the tony lane → two identical leaf
  pages (faithful mirror of the registry; harmless).
- `ada-cms-pages-mn` pages now render on the public cms edge — same
  posture as the kk lane (behind Cloudflare Access, no app auth). Flag
  if mn pages should stay tailnet-only.

## lessons:
- Memory docs carry prose `subject` values, not just slugs — don't
  assume slug-shaped join keys in bank tables.
- ada-cms-pages /search is capped by `limit` and returns first-N docs —
  verify pages by `/get` per key, not a collection scan.
- cms-render `resolve()` only tries collections in `COLLECTIONS` —
  writing to a new lane collection means registering it there or pages
  404.
- Two registry banks can share one collection (`personal` +
  `personal-tony` → `ada-ha-bank-personal-tony`); snapshot tools should
  expect duplicate leaf content.
- bank-inspect.py resolves repo SSOT via `parents[2]` — to run it
  standalone on another host, stage `<tmp>/scripts/ada/` + a `docs`
  symlink to a real checkout.
