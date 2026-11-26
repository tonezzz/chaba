# chaba/ansible — host baseline management

Ansible scaffold for the chaba fleet. Companion to (not a replacement for)
`scripts/audit-hosts.py` + `docs/ssot/infrastructure/ssot.audit.hosts.yml`
— the audit runner *observes* drift; Ansible *converges* declared state.

## Layout

```
ansible.cfg               # inventory + become defaults
inventory/hosts.yml       # all hosts, groups, tailscale IPs (SSOT-linked)
inventory/group_vars/all.yml   # common_packages, unattended-upgrades policy
inventory/host_vars/<host>.yml  # per-host opt-ins (e.g. docker_enabled)
inventory/group_vars/ocb_pane.yml   # declared ada-ocb pane contract (pins, units, edge)
playbooks/site.yml        # baseline: packages, security updates, docker check
playbooks/host-load-guard.yml    # CPU-job wrapper, slice, thermal gate, alarms, HA telemetry
playbooks/ha-dashboard-deploy.yml  # idempotent chaba-admin Hosts view promotion
playbooks/ada-ocb-audit.yml   # read-only pane surface probe + durable artifact
playbooks/ada-ocb-verify.yml  # contract gate (producer + consumer), nonzero on drift
playbooks/ada-ocb-upgrade.yml # approval-gated write path (starts the host's update unit)
playbooks/vars/ada-ocb-upgrade.yml  # safety defaults: ocb_change_approved=false
playbooks/tasks/ada-ocb-{probe,edge-probe,assert}.yml  # shared probes + shared gate
playbooks/templates/ada-ocb-audit.j2       # audit report renderer
```

## ada-ocb pane audit + verify (read-only)

The OpenChamber pane already has its own upgrade executor on idc02
(`openchamber-update.service` + monthly timer — npm install, fail-loud
`models.status` patch re-apply, restart). Ansible does **not** duplicate that
installer. These two playbooks make the declared state inspectable and gateable:

```bash
cd ansible
ansible-playbook playbooks/ada-ocb-audit.yml              # probe both pane hosts + public edge
ansible-playbook playbooks/ada-ocb-audit.yml --limit idc02
ansible-playbook playbooks/ada-ocb-verify.yml             # gate: exit 2 on drift
ansible-playbook playbooks/ada-ocb-verify.yml --limit idc02
```

- `ocb_pane` group = **idc02 (primary)** + **tony-dell (soak fallback)**.
  Only `primary` is held to the declared version pins + models.status patch;
  the pre-migration fallback's drift is reported as INFO, not a gate failure.
- Pins live in `inventory/group_vars/ocb_pane.yml` **and** are cross-checked
  against `ssot.audit.hosts.yml` at runtime — a stale pin fails the gate rather
  than blessing the wrong version.
- Both playbooks are read-only on every target; probes carry `check_mode: no`
  so `--check` still yields genuine evidence. Artifacts land in
  `reports/ada-ocb/<host>.yml` (gitignored).
- **Producer proof** (unit/timer active, loopback bind, local 200, patch marker,
  startup.env 600, litellm drop-in) and **consumer proof** (public edge 200 +
  CSP `frame-ancestors`) are both required — a healthy service behind a broken
  edge is a failure.
- No secrets are read into Ansible; the probe only checks that `startup.env`
  is mode 600 and that the drop-in references `litellm-ada.env`.
### Ada-OCB upgrade (approval-gated — built, not yet executed on prod)

`ada-ocb-upgrade.yml` is the write path, but it is inert by default:

```bash
cd ansible
ansible-playbook playbooks/ada-ocb-upgrade.yml --check --diff   # preview; no write
ansible-playbook playbooks/ada-ocb-upgrade.yml                  # still no write (default)
# only after explicit SAME-SESSION approval:
ansible-playbook playbooks/ada-ocb-upgrade.yml -e ocb_change_approved=true
```

- Ansible does **not** implement the upgrade — it starts idc02's existing
  `openchamber-update.service` (oneshot: npm install → fail-loud patch
  re-apply → restart). `--check` is a genuine simulation because the shell
  write is guarded by `not ansible_check_mode`, so even
  `-e ocb_change_approved=true --check` starts nothing.
- Rollback (restore the Caddy route line + reload) is printed on the
  controller **before** the write task. A failed unit exits nonzero and the
  play stops; no half-applied state.
- Post-upgrade reuses `tasks/ada-ocb-assert.yml` — the *exact* gate
  `ada-ocb-verify.yml` runs — so the write cannot be declared good without
  producer + consumer proof.
- The `systemd` module cannot reach the user bus over SSH on idc02
  (`Failed to connect to bus`), hence the guarded `systemctl --user` shell
  path. Do not "improve" it back to the module without re-testing check mode.
- The host unit pins `@openchamber/web@2.7.3` but installs `@opencode/cli`
  bare. On 2026-11-24 the live upgrade moved CLI 2.3.2 → 2.4.1 and Tony
  **accepted 2.4.1** (DEV-0020) rather than changing the host unit. The
  declared pin in `group_vars/ocb_pane.yml` and SSOT now tracks 2.4.1; the
  playbook never edits host units. Expect CLI to float on future updates —
  if the pane breaks, this pin is the first thing to re-check.

## Install ansible (once, on the controller — any tailnet host)

```bash
sudo apt install ansible        # Ubuntu 24.04+: ansible-core 2.x
# or: pipx install ansible / pip install ansible-core
```

## Usage

```bash
cd ansible

# Connectivity check (safe)
ansible baseline -m ping

# Dry run — shows what would change, touches nothing
ansible-playbook playbooks/site.yml --check --diff

# Apply baseline to workstations + vps
ansible-playbook playbooks/site.yml

# Single host
ansible-playbook playbooks/site.yml --limit tony-dell

# Portable laptops — always explicit (they sleep / leave the tailnet)
ansible-playbook playbooks/site.yml --limit mn01

# kk-mac is macOS — not in `baseline`; manage separately when needed
ansible kk-mac -m ping

# Fleet disk-headroom audit (read-only; also feeds disk-trend history)
ansible-playbook playbooks/disk-headroom.yml --check --diff   # real dry-run
ansible-playbook playbooks/disk-headroom.yml                  # probe + write
ansible-playbook playbooks/disk-headroom.yml --limit tony-dell

# Fleet MCP verification audit (read-only; tailnet/MCP config required on host)
ansible-playbook playbooks/audit-mcp-verify.yml --check --diff
ansible-playbook playbooks/audit-mcp-verify.yml
ansible-playbook playbooks/audit-mcp-verify.yml --limit tony-dell
```

`disk-headroom.yml` specifics:

- **Controller self-detect** — the playbook matches the machine it runs on
  against the inventory (`ansible_host` IP ∈ local addresses, or inventory
  name == hostname/fqdn) and probes that host with
  `ansible_connection=local`. SSH-to-self over the tailnet IP has no key
  path (OPS-0019). If detection picks wrong, override:
  `-e self_host=idc02`.
- **`--check --diff` is a real dry-run** — the df probe is read-only and
  runs anyway (`check_mode: no`), so verdicts and diffs are genuine;
  file writes (verdict reports, history append) are skipped.
- **Feeds the trend** — each probed host's mounts are appended to
  `DISK_TREND_HISTORY` (default `~/var/chaba/health/disk-trend.jsonl`),
  the same jsonl `scripts/ada/disk-trend-watch.py` writes, keyed by the
  `ssot.audit.hosts.yml` host name (`tony-macbook`→`macbook`). Hosts
  skipped by `--limit` write nothing — a skipped laptop must not record
  a false `unreachable` sample. Disable with `-e disk_trend_feed=false`.
- Verdict reports land in `reports/ansible-benchmark/disk/<host>.yml`.

`audit-mcp-verify.yml` specifics:

- **Read-only probe** — runs `scripts/verify-all-mcp-servers.py --json` from
  each host's `~/CascadeProjects/chaba` checkout (override with
  `-e chaba_repo_path=...`). Hosts without a checkout or MCP config are
  reported as `skipped`, not failed.
- **Controller self-detect** — same as `disk-headroom.yml`: the controller
  probes itself via `ansible_connection=local` to avoid ssh-to-self key
  issues. Override with `-e self_host=<name>`.
- **`--check --diff` is a real dry-run** — the probe is read-only and runs
  anyway (`check_mode: no`); report writes are skipped.
- Verdict reports land in `reports/ansible-benchmark/mcp/<host>.yml`.

## SSH known_hosts (host_key_checking)

`ansible.cfg` keeps `host_key_checking = True` — no `StrictHostKeyChecking
-no` shortcuts. Because `ansible_host` values are **Tailscale IPs**, ssh
checks the key against the *IP*, so each controller needs the IP in
`~/.ssh/known_hosts`. Existing hashed entries made by ssh'ing a hostname
do **not** match (`|1|…` hashes are keyed on the exact name/IP asked for).

Seed all inventory IPs once per controller with the bootstrap playbook
(replaces the old hand-written `ssh-keyscan` snippet):

```bash
cd ansible
ansible-playbook playbooks/ssh-bootstrap.yml --check --diff  # preview
ansible-playbook playbooks/ssh-bootstrap.yml                 # seed hashed IPs
```

It uses `ansible.builtin.known_hosts` with `hash_host: true` — hashed IPs
still match and known_hosts stays non-enumerable. Primary tailnet IPs are
gated; declared LAN aliases (`tony-dell-lan`) are best-effort so an off-LAN
box does not fail a bootstrap. Retired idc01 is never scanned. The
controller's own host key is not needed: self is probed via
`ansible_connection=local`, not ssh.

## SSH access contract (read-only verifier)

`playbooks/ssh-mesh-verify.yml` gates the declared SSH access contract in
`inventory/hosts.yml` + `group_vars/all.yml` (`ssh_user`, `ssh_port`,
`ssh_identity_file`, `ssh_network`, `ssh_enabled`, `ssh_push_chaba`,
`ssh_push_repo_path`) against the live mesh. (`ssh_push_repo_path` is a
verifier-specific path so it can stay in `~` form — unlike `chaba_repo_path`,
which `session_capture.yml` renders verbatim into systemd units.) The
verifier never writes: `ssh-mesh-sync.sh` remains the writer of
`authorized_keys`, while `ssh-bootstrap.yml` owns controller `known_hosts`.
No private key is read into Ansible — only the pubkey path named by
`ssh_identity_file`.

Generate the controller's aliases from the same declarations:

```bash
cd ansible
ansible-playbook playbooks/ssh-config-render.yml              # read-only block + sha256
ansible-playbook playbooks/ssh-config-generate.yml --check --diff  # preview
ansible-playbook playbooks/ssh-config-generate.yml            # write (keeps a .bak-*)
```

`blockinfile` owns one marked block at the top of `~/.ssh/config`; all other
stanzas (github-*, camwall-*, operator additions) are preserved byte-for-byte
and the file is tightened to mode 0600. The rendered block is a pure inventory
function (literal `~` identity paths), so it is byte-identical on every
controller — verified from tony-omen, tony-dell and idc02 at SHA
`c126240bd94e41182015417520594b840da724e4631a0b7e40c35bada6a37e14`. idc01 is
excluded via the `disabled` group; kk-mac is generated (fixing its old missing
`User`) while staying out of the reachability gate via `ssh_enabled: false`.

```bash
cd ansible
ansible-playbook playbooks/ssh-mesh-verify.yml              # gate: exit 2 on drift
ansible-playbook playbooks/ssh-mesh-verify.yml --limit vps  # one group
ansible-playbook playbooks/ssh-mesh-verify.yml --limit mn01 # off-net laptop only
ansible-playbook playbooks/ssh-mesh-verify.yml -e ssh_strict=false  # survey, no gate
```

Four legs are asserted: BatchMode reachability, this controller's declared
identity in the host's `authorized_keys`, a live `git push --dry-run` for
every host declaring `ssh_push_chaba`, and `ssh_user` == effective
`ansible_user`. A fifth check — `ssh -G <alias>` user vs declared user — is
reported; after running `ssh-config-generate.yml` it reads `MATCH` for kk-mac,
which had no `User` line before generation. Pass creds
were probed 2026-11-24 on idc02, idc03, tony-omen, tony-dell and mn01 before
declaring them. Retired hosts (`ssh_enabled: false`, i.e. idc01) are always
excluded. Use `--limit` for sleeping laptops; `ssh_strict=false` downgrades
asserts to warnings for a broad survey.

## Inventory notes

- `ansible_host` uses **Tailscale IPs** — works from any tailnet node.
- `idc01` is under `disabled:` (retired 2026-11-14) — never target it.
- SSH auth relies on `~/.ssh/config` keys already working; no vault needed
  for the baseline playbook.

## Conventions

- Keep `site.yml` safe: no dist-upgrades, no firewall changes, no service
  restarts beyond the declared handlers.
- New host → add to `inventory/hosts.yml` + a `inventory/host_vars/<host>.yml`, and
  update `ssot.host-roles.yml` / `ssot.audit.hosts.yml` so the audit
  contract and the playbook stay in sync.
- After running, `python3 scripts/audit-hosts.py --host <h>` should show
  no unexpected drift.

## Runner tool convergence (all pinned tools)

`deploy-runner-agent.yml` only covered `runner-agent`; the other pinned tools
in `scripts/devin/runner-tooling.manifest.json` drifted because they were
repaired ad-hoc (`scp`). The canonical path is now:

```bash
cd ansible
ansible-playbook playbooks/deploy-runner-tools.yml --check --diff   # read-only
ansible-playbook playbooks/deploy-runner-tools.yml                  # apply
ansible-playbook playbooks/audit-runner-tools.yml                   # re-audit
```

`deploy-runner-tools.yml` copies every pinned tool, verifies the installed
sha256 against the manifest, uses `serial: 1` and a non-blocking restart
handler, and is safe to call from cron. `scripts/devin/runner-tools-converge.sh`
wraps check → apply → audit → board re-arm → re-audit, and
`install-runner-tools-converge.yml` installs the daily user timer on managed
hosts. Drift found by `audit-runner-tools.yml` is turned into a board card by
`scripts/board/runner-drift-rearm.py` (use `--dry-run` to parse without
writing); `--verify` comments the re-audit result and closes the card when
clean.

## HA temperature telemetry + dashboard (tony-omen)

Two playbooks own the per-zone temperature history shown on the `chaba-admin`
Hosts view. Both are tony-omen-only and tagged `ha` so they can be converged
together. Always pass an explicit `--limit`:

```bash
cd ansible
# wrapper, CPU slice, thermal policy, alarms, and the HA telemetry mirror
ansible-playbook playbooks/host-load-guard.yml --check --diff --limit tony-omen --tags ha
ansible-playbook playbooks/host-load-guard.yml --limit tony-omen --tags ha

# stage snapshot + helper, probe, back up, promote only the `hosts` view,
# then verify the entities over HA's REST API
ansible-playbook playbooks/ha-dashboard-deploy.yml --check --diff --limit tony-omen --tags ha
ansible-playbook playbooks/ha-dashboard-deploy.yml --limit tony-omen --tags ha
```

- `host-load-guard.yml` also carries `thermal`, `wrapper`, `slice` and
  `alarms` tags. `playbooks/vars/thermal.yml` is the single place to change
  admission thresholds; re-run the `thermal` slice to push them.
- The telemetry script publishes numeric per-zone sensors
  (`sensor.<dev>_temp_<zone>`). Its user timer runs every 5 minutes and picks
  up a new script on the next tick — no service restart is needed.
- `ha-dashboard-deploy.yml` treats
  `docs/home-assistant/dashboards/chaba-admin-current.json` as the source of
  truth for the `hosts` view only; the other prod views are preserved. It
  backs up `.storage/lovelace.chaba_admin` only before an actual write, and
  `--check` previews staged file diffs while skipping all websocket/API tasks.
- The HA token stays in a 0600 host-side secret file — never in play vars or
  command arguments. `promote-views.py` prints `already current` when the view
  matches, which keeps the promote task idempotent (`changed=0`).
