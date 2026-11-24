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
playbooks/ada-ocb-audit.yml   # read-only pane surface probe + durable artifact
playbooks/ada-ocb-verify.yml  # contract gate (producer + consumer), nonzero on drift
playbooks/tasks/ada-ocb-{probe,edge-probe}.yml  # shared one-round-trip probes
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
- Prod writes (an `ada-ocb-upgrade.yml`) remain out of scope until explicitly
  approved in-session; when added it must start the host's existing update
  unit, not reimplement `npm i -g`.

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

## SSH known_hosts (host_key_checking)

`ansible.cfg` keeps `host_key_checking = True` — no `StrictHostKeyChecking
-no` shortcuts. Because `ansible_host` values are **Tailscale IPs**, ssh
checks the key against the *IP*, so each controller needs the IP in
`~/.ssh/known_hosts`. Existing hashed entries made by ssh'ing a hostname
do **not** match (`|1|…` hashes are keyed on the exact name/IP asked for).

Seed all inventory IPs once per controller:

```bash
cd ansible
ansible-inventory --list \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)
print("\n".join(sorted({v["ansible_host"] for g in d.values()
  for v in (g.get("hosts") or {}).values()
  if isinstance(v, dict) and "ansible_host" in v})))' \
  | xargs -I{} sh -c 'ssh-keyscan -H {} >> ~/.ssh/known_hosts 2>/dev/null'
```

(`ssh-keyscan -H` hashes the IP — it still matches, and known_hosts stays
non-enumerable.) The controller's own host key is not needed: self is
probed via `ansible_connection=local`, not ssh.

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
