# Dispatch outcome — litellm-ledger-timer-enable

Card: `litellm-ledger-timer-enable` (ref OPS-1361)
Date: 2026-11-25 · Host worktree: idc02 · Target host: idc03

## What changed

- `stacks/idc03/litellm/deploy.sh` — **root-cause fix**: moved
  `litellm-ledger.service`/`.timer` from `FILES` (installed to
  `~/.config/containers/systemd/`, the podman quadlet source dir that
  systemd never reads for plain units) to `USER_UNITS`
  (`~/.config/systemd/user/`). This is why the timer was never just
  "disabled" — it was unloadable.
- `stacks/idc03/litellm/stack.yml` — ledger note updated: timer enabled
  2026-11-25, units live in `~/.config/systemd/user/`.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — idc03 timer census:
  added `litellm-ledger.timer` and `litellm-budget-watch.timer` (the
  latter was enabled earlier today by the sibling dispatch but never
  census-declared — same one-line gap).
- `docs/ssot/jobs/infrastructure/2026-11-25-litellm-ledger-timer.yml` —
  job trail (decision + verification).
- Live on idc03: scp'd both units to `~/.config/systemd/user/`
  (sha256-identical to repo), removed the inert copies from
  `~/.config/containers/systemd/`, `daemon-reload`,
  `enable --now litellm-ledger.timer`.

## Result — DONE condition met

- `systemctl --user list-timers litellm-ledger.timer` → enabled,
  NEXT Thu 2026-11-26 07:10:00 +07 (daily, Persistent=true).
- `systemctl --user start litellm-ledger.service` (the exact unit the
  timer activates) → exit 0/SUCCESS; journal shows `podman exec
  litellm-db psql` SpendLogs read then `published →
  ada-cms-pages/llm-gateway-spend-ledger`.
- Consumer proof: MDDB `/v1/get` on `ada-cms-pages`/
  `llm-gateway-spend-ledger` → `meta.updated=2026-11-25T03:40:54Z`,
  fresh trailing-24h table (total **$8.841524**, source
  `postgres:LiteLLM_SpendLogs`). The ~11.8-day-stale page is now fresh.
- `scripts/litellm/daily-ledger.py` on idc03's exec checkout is
  md5-identical to repo; `~/.config/secrets/litellm-keys.env` present.

## How to verify

```
ssh idc03 'systemctl --user list-timers litellm-ledger.timer'
ssh idc03 'systemctl --user status litellm-ledger.service'
ssh idc03 'journalctl --user -u litellm-ledger.service -n 20'
curl -s -X POST http://100.102.134.91:11027/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"ada-cms-pages","key":"llm-gateway-spend-ledger","lang":"en"}'
```

Next scheduled publish: 2026-11-26 07:10 +07.

## Lessons

- `~/.config/containers/systemd/` is the podman **quadlet source** dir —
  `.service`/`.timer` files dropped there are silently never loaded.
  Plain user units belong in `~/.config/systemd/user/`; quadlets
  (.container/.pod/…) belong in containers/systemd. deploy.sh had them
  mixed in one FILES array.
- `Persistent=true` does NOT make a brand-new timer fire immediately —
  there is no last-trigger stamp to catch up from. To verify a fresh
  OnCalendar timer's payload, `systemctl --user start <name>.service`
  directly rather than waiting for the next elapse.
- Timer census in `ssot.audit.hosts.yml` declares `.timer` units, not
  the oneshot `.service` they activate (dispatch-wt-clean precedent);
  failed oneshots still surface via the failed-units loop.
