# dispatch-outcome — ansible disk-headroom.yml hardening (2026-11-23)

## What changed

**`ansible/playbooks/disk-headroom.yml`** — restructured into a single
play and hardened on all four card requirements:

1. **Controller auto-local** — play vars compute `controller_idents`
   (controller's own IPs via `hostname -I`, plus `hostname`/`hostname -f`,
   all `errors='ignore'` pipe lookups so non-Linux controllers survive) and
   `controller_self` (first audited host whose `ansible_host` or inventory
   name matches). A `pre_tasks` `set_fact: ansible_connection=local` fires
   for that host before any ssh is attempted — fixes the idc02
   ssh-to-self publickey failure (OPS-0019). Override: `-e self_host=<name>`.
2. **Real `--check --diff`** — the df probe is read-only so it runs under
   check mode (`check_mode: no`) giving genuine verdicts; `file`/`template`/
   `lineinfile` honor check mode natively and show diffs; alerts re-render
   `disk-headroom.j2` in memory via `lookup()` so they're correct even
   though verdict files aren't written.
3. **Trend feeding** — each probed host appends one jsonl record to
   `DISK_TREND_HISTORY` (default `~/var/chaba/health/disk-trend.jsonl`,
   same env override as `disk-trend-watch.py`) in the watcher's exact
   record shape (`ts`/`epoch`/`host`/`unreachable`/`mounts[]`/`dirs`),
   keyed by the `ssot.audit.hosts.yml` name (`tony-macbook`→`macbook`).
   Gates: only hosts actually probed this run (`diskprobe` defined —
   `--limit`-skipped hosts must not record a false `unreachable`) and only
   hosts present in `audit_ssot['hosts']`. Probe JSON now emits `used_kb`
   (slope math needs it). `-e disk_trend_feed=false` disables.
4. **host_key_checking documented** — stays `True` in ansible.cfg; README
   gains an "SSH known_hosts" section explaining that tailnet-IP
   `ansible_host` values need the *IP* in `~/.ssh/known_hosts` (hashed
   hostname entries never match), with an inventory-wide
   `ssh-keyscan -H` seeding one-liner.

**Structural fix along the way**: the original dedicated
`hosts: localhost` eval play was filtered out by *any* `--limit` ("no
hosts matched") — limited runs wrote no reports at all. Eval is now
`delegate_to: localhost` + `run_once` tasks at the end of the probe play,
so `--limit` can't strip it. The verdict template also distinguishes
`probed: false` ("not probed — outside this run's targets") from real
`unreachable`.

**Files**: `ansible/playbooks/disk-headroom.yml` (rewritten),
`ansible/playbooks/templates/disk-headroom.j2` (probed/unreachable split
+ `used_gib`), `ansible/README.md` (disk-headroom usage + SSH known_hosts
section), `docs/ssot/jobs/infrastructure/2026-11-23-ansible-disk-headroom-harden.yml`
(decision/runbook trail).

## Verified (on tony-macbook)

- `--syntax-check` clean.
- `--check --diff --limit tony-macbook`: `controller_self=tony-macbook`
  detected, local conn applied, probe ran under check, verdict diffs and
  the history-append diff rendered, alerts printed correctly
  (`tony-macbook: ok (2 mounts)`, others `not probed`).
- Real run `--limit tony-macbook` with `DISK_TREND_HISTORY` redirected to
  a worktree file: wrote one valid record `{"host": "macbook", ...}`.
- `disk-trend-watch.py --history <file> --report` ingests it: macbook
  appears with both mounts (slope n/a until a 2nd sample — expected,
  MIN_SPAN_H gate).
- Second `--check` run: idempotent (verdict files unchanged; only the
  append shows `changed` — correct for append semantics).

## Notes / follow-ups flagged

- `ssot.audit.hosts.yml` ~line 431 (`focus-dispatcher-overnight.service`
  known_failed entry) has a duplicate `action:` key — PyYAML keeps the
  last, ansible prints a duplicate-mapping warning. Pre-existing data
  smell, not fixed here.
- `probe_ts` renders naive-UTC (`now(utc=True)` lacks `%z` on this
  ansible) — cosmetic; disk-trend keys all math on `epoch` and never
  parses `ts`.
- Not run against the full fleet from this worktree — remote SSH probes
  and writes to the real `~/var/chaba/health/disk-trend.jsonl` are for a
  merged production run.

lessons:
- `hosts: localhost` plays are filtered out by any --limit ("no hosts matched") — put controller-side work in delegate_to:localhost + run_once tasks inside the targeted play instead.
- set_fact never opens a connection, so `set_fact: ansible_connection=local` in pre_tasks is a safe way to give the controller host local probing before its first ssh task.
- command/shell probes that are genuinely read-only should carry check_mode:no — then --check --diff produces real verdicts instead of skipped gates.
- Loop-scoped lookup('template', ...) renders with the loop_var in context — a cheap way to re-render a template in memory for alerts under --check without reading files that weren't written.
- When appending samples to a shared trend file, gate on "was this host actually probed" (registered result defined), not on mount presence — otherwise --limit-skipped hosts record false 'unreachable' rows.
