# Dispatch outcome — jevos-idc02-earlyoom-kill (OPS-1516)

## Decision

Chose **option (a)**: `--avoid '(^|/)(jev)$'` added to `EARLYOOM_ARGS` in
`/etc/default/earlyoom` on idc02, `earlyoom.service` restarted — **applied
and verified live**.

Rejected (b) `Restart=always` on jevos.service: under sustained memory
pressure earlyoom would kill→restart→kill loop (each restart reallocates
~1.7 GiB RSS, worsening the pressure) and `systemctl --user stop` would
stop sticking for maintenance. Rejected (c) accept+alert: detection without
availability — the lane already proved it dies silently ~17 min. An
inactive-unit alert is still a worthwhile follow-up for OTHER units.

## What changed

- `ansible/playbooks/earlyoom-avoid-jev.yml` — new single-host,
  approval-gated playbook (same pattern as `idc03-memory-guard.yml`).
  lineinfile rewrites the one uncommenting EARLYOOM_ARGS line
  (`backup: true` + `sh -n` validation), handler restarts earlyoom,
  verify tasks assert active state, running argv, regex semantics, and
  jev `/health`.
- `docs/ssot/jobs/infrastructure/2026-11-27-idc02-jevos-earlyoom-avoid.yml`
  — full job trail (decision, quoting proof, verification, rollback,
  lessons).

## Verification (all live on idc02)

- `pgrep -a earlyoom` → `/usr/bin/earlyoom -r 3600 --avoid (^|/)(jev)$`
- `systemctl is-active earlyoom.service` → active, restarted 21:32:58 +07
- `curl http://100.123.163.11:8017/health` → 200
- Regex sanity: comm `jev` matches; `openjev`/`jev-serve` do not
- Idempotent: second `--check --diff` → changed=0
- Backup: `/etc/default/earlyoom.1398770.2026-11-27@21:32:57~`

Quoting was proven before writing the play: a `systemd-run` transient unit
with an EnvironmentFile showed systemd's `$VAR` word-splitting honors the
single quotes, so earlyoom receives the clean regex argv (same pattern as
Debian's own example).

## Caveats / follow-ups

- Config-level verification only; behavioral proof needs the next real
  mem<10% event (earlyoom logs every victim decision).
- **openjev is the bigger exposure**: comm=`openjev`, ~2.5 GiB RSS (the
  largest process on idc02) and still earlyoom-killable. The anchored
  regex deliberately does not exempt it — out of scope, worth a card.
- Inactive-unit alerting (option c's mechanism) would still help catch
  OTHER silent unit deaths — candidate follow-up card.
- Follow-up carded: **OPS-1517 `openjev-idc02-earlyoom-exposure`**
  (backlog, medium) — openjev protection decision on idc02.

## How to verify

```
ssh idc02 'pgrep -a earlyoom; systemctl is-active earlyoom.service; \
  curl -s -o /dev/null -w "%{http_code}" http://100.123.163.11:8017/health'
grep EARLYOOM_ARGS /etc/default/earlyoom
cd ansible && ansible-playbook playbooks/earlyoom-avoid-jev.yml --check --diff --limit idc02
```

lessons:
- ansible `command`/`shell` tasks are SKIPPED in --check mode unless the task sets `check_mode: false` — read-only probes need it or registered vars come back empty and downstream asserts fail confusingly.
- `earlyoom -h` writes help to stderr, not stdout — assert on `stdout ~ stderr`.
- systemd EnvironmentFile + `ExecStart=$VAR` word-splitting honors single quotes in the value (verified via systemd-run) — Debian's --avoid quoting example is correct as-is.
- earlyoom `--avoid` matches process comm: `(^|/)(jev)$` exempts `jev` but NOT `openjev` — check every co-tenant's comm before anchoring.
