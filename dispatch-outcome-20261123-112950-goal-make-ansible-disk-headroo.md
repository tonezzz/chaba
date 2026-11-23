# dispatch-outcome — ansible-disk-headroom-harden (attempt 2)

## What happened

Attempt 1 (session boom-submarine, commit `6ffb910078`) had already done the
whole job and reported "done in worktree" on the card at 11:14, but the
session ended before pushing the outcome doc / final comms — the checkpoint
commit lived only on its own dispatch branch. Attempt 2 cherry-picked that
commit, resolved two conflicts against the newer `underused` signal that
landed in the meantime (commit `c9de6447b4` / `970a4175b5` era), verified
end-to-end, and fixed two small gaps found during verification.

## Changes (all staged in this worktree, 4 files)

- `ansible/playbooks/disk-headroom.yml` — rewritten as a single play:
  1. **Controller self-detect** — `controller_idents` (local IPs via
     `hostname -I` + `hostname`/`hostname -f`) matched against inventory
     `ansible_host` values / names → `ansible_connection=local` via a
     `pre_tasks` `set_fact`. Override: `-e self_host=<name>`.
  2. **Real `--check --diff`** — the df probe is read-only and runs under
     check mode (`check_mode: no`); verdict template and history-append
     diffs are computed but no writes land.
  3. **Trend feed** — appends one jsonl record per probed host to
     `DISK_TREND_HISTORY` (default `~/var/chaba/health/disk-trend.jsonl`),
     exact `disk-trend-watch.py` shape (`ts/epoch/host/unreachable/
     mounts/dirs`, mounts carry `used_kb` for slope), keyed by the
     `ssot.audit.hosts.yml` name (`ssot_key_map`: tony-macbook→macbook).
     Gated on `diskprobe is defined` so `--limit`-skipped hosts never
     record a false `unreachable`, and on the host being ssot-known.
     Disable: `-e disk_trend_feed=false`.
  4. **host_key_checking documented** — stays `True`; seed tailscale IPs
     into `~/.ssh/known_hosts` via `ssh-keyscan -H` (hashed hostname
     entries don't match IP lookups). Docs in playbook header +
     `ansible/README.md` "SSH known_hosts" with an inventory-wide seed
     one-liner.
- `ansible/playbooks/templates/disk-headroom.j2` — adds `probed` flag
  (distinct from `unreachable`); summary reads "not probed (outside this
  run's targets)" for `--limit`-excluded hosts; rows carry `used_gib` and
  keep the `underused`/`underused_mounts` fields from master.
- `ansible/README.md` — usage block, `disk-headroom.yml` specifics,
  SSH known_hosts section.
- `docs/ssot/infrastructure/ssot.audit.hosts.yml` — removed a duplicate
  `action:` key on `focus-dispatcher-overnight.service` (YAML last-wins
  already resolved it to `investigate`; behavior-preserving, kills the
  duplicate-key warning the playbook's `from_yaml` load triggered).
- New: `file` task creates the `disk_trend_history` parent dir when
  missing (fresh controllers); no `mode:` so it never chmods an existing
  dir.

## Verification (on tony-macbook, ansible-core 2.22.0)

- `ansible-playbook playbooks/disk-headroom.yml --syntax-check` → clean.
- `--limit tony-macbook --check --diff` → `controller_self=tony-macbook
  (probes itself locally)`, verdict diffs rendered, history line shown in
  diff but not written.
- `--limit tony-macbook` real run with `DISK_TREND_HISTORY=/tmp/dt-test.jsonl`
  → appended `{"host":"macbook","unreachable":false,"mounts":[2],"dirs":[]}`
  — same keys `load_history`/`mount_trends` in disk-trend-watch.py read.
- Full-fleet `--check` → 7/7 hosts probed (macbook local, 6 over ssh),
  all `ok`, zero unreachable, verdicts + appends diffed but nothing
  written (`~/var/chaba/health/disk-trend.jsonl` confirmed absent after).

## Result

Done — all 4 spec items implemented and verified. Card
`ansible-disk-headroom-harden` can move to review; promote by merging this
branch (staged diff only, no commits/pushes made by me).

lessons:
- A completed attempt can leave a clean checkpoint commit on the old dispatch branch — cherry-pick it instead of redoing the work (card comms "done in worktree" is the tell).
- `file state=directory mode=...` chmods existing dirs too — omit `mode` when the path may already exist (a `/tmp` env override hit EPERM).
- `lookup ... | from_yaml` surfaces duplicate YAML keys in SSOT files that `include_vars` also trips on — worth a lint.
- Dedicated `hosts: localhost` eval plays are silently dropped by `--limit`; `delegate_to: localhost` + `run_once` inside the probe play survives it.
