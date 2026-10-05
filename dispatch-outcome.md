# Dispatch outcome — cms-generator-schedule-audit

## Finding

Every `scripts/ada/*.py` generator that publishes `ada-cms-pages` or writes
report artifacts is **already scheduled** — the card's premise (no per-script
units, absent from overnight-jobs-expanded.sh) was technically true but
misleading: nearly all run inside two chain timers, verified live on all
four hosts via `systemctl --user list-timers`:

- `ada-review-refresh.timer` (daily 08:45, tony-omen) → `export-transcripts.py`
  chain → journal/host/ha/logs-report, log-shipper, vocab-pages-sync,
  prune-old-docs, bloat-report, 7 personal-tier collectors (devin/net/ops/
  tasks/spend/caddy/ha-events), personal-rollup, focus-rollup — 16 generators.
- `kanban-sync.timer` (15min, tony-dell, rendered job) → cms-auto-health,
  logs-kanban, kanban-stats, kanban-cms.
- Dedicated: chaba-services-regen (host-services-cms), ada-flood-news
  (flood-news-update), news-flood (news-flood-fetch), weekly-digest,
  ada-embed-bench (embed-bench --publish), chaba-audit suite → cms-pages-live
  (cms-audit --publish) + CI lane.
- Event-driven: session-report.py at each Ada session end (ada-pi).
- manual-on-purpose: cms-normalize-meta, transcript-index (no callers —
  superseded diagnostic), plus the out-of-scope tools. dead: none.

So **no new generator timers were needed**. The real gap was failure
visibility and registry drift.

## Changes (repo only — no live installs, per dispatch rules)

- `systemd/ada-report-fail@.service` — NEW templated failure reporter
  generalizing `chaba-services-regen-fail.service`: board comms POST
  (CARD env, default `cms-generator-schedule-audit`) + focus-inbox fallback.
- `OnFailure=ada-report-fail@%p.service` added to `ada-review-refresh.service`,
  `weekly-digest.service`, `news-flood.service` (hand-maintained units).
- `scripts/render-jobs.py` — new `on_failure:` job field → `OnFailure=` in
  rendered `[Unit]`; used by the `kanban-sync` job in `ssot.jobs.yml`;
  `systemd/generated/tony_dell/kanban-sync.service` re-rendered.
- `docs/ssot/infrastructure/ssot.automation.yml` v8 — `ada_cms_generators`
  section: per-generator {scheduled|manual-on-purpose|dead} + scheduler +
  outputs, so the next audit doesn't re-check.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — registered missing timers:
  tony-omen (ada-review-refresh, weekly-digest), tony-dell (kanban-sync,
  ada-flood-news), idc01 (news-flood, ada-embed-bench), idc02 (ada-flood-news,
  devin-bank-distill, chaba-system-report).
- `docs/ssot/jobs/ada/2026-10-05-cms-generator-schedule-audit.yml` — audit trail.

Deliberately skipped: `OnFailure` on ada-flood-news (exits 2 on all-skipped
ticks — would spam the board every 15min).

## Drift found (needs operator action)

Post-migration duplicate timers firing on BOTH sides:

- `ada-flood-news.timer` — tony-dell + idc02 (canonical: idc02)
- `devin-bank-distill.timer` — tony-omen + idc02 (canonical: idc02)
- `chaba-system-report.timer` — tony-dell + idc02 (canonical: idc02)

Retire stale copies: `systemctl --user disable --now <unit>` on dell/omen.

## Verify

```
python3 scripts/render-jobs.py --check     # OK 21 jobs
node scripts/ssot-validate-all.mjs         # 1176 valid, 0 errors
systemd-analyze verify --user systemd/ada-report-fail@.service ...
```

After merge, sync units on each host (copy + `daemon-reload`); the
OnFailure lines are inert until `ada-report-fail@.service` exists on that host.
