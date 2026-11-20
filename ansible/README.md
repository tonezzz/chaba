# chaba/ansible — host baseline management

Ansible scaffold for the chaba fleet. Companion to (not a replacement for)
`scripts/audit-hosts.py` + `docs/ssot/infrastructure/ssot.audit.hosts.yml`
— the audit runner *observes* drift; Ansible *converges* declared state.

## Layout

```
ansible.cfg               # inventory + become defaults
inventory/hosts.yml       # all hosts, groups, tailscale IPs (SSOT-linked)
group_vars/all.yml        # common_packages, unattended-upgrades policy
host_vars/<host>.yml      # per-host opt-ins (e.g. docker_enabled)
playbooks/site.yml        # baseline: packages, security updates, docker check
```

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
```

## Inventory notes

- `ansible_host` uses **Tailscale IPs** — works from any tailnet node.
- `idc01` is under `disabled:` (retired 2026-11-14) — never target it.
- SSH auth relies on `~/.ssh/config` keys already working; no vault needed
  for the baseline playbook.

## Conventions

- Keep `site.yml` safe: no dist-upgrades, no firewall changes, no service
  restarts beyond the declared handlers.
- New host → add to `inventory/hosts.yml` + a `host_vars/<host>.yml`, and
  update `ssot.host-roles.yml` / `ssot.audit.hosts.yml` so the audit
  contract and the playbook stay in sync.
- After running, `python3 scripts/audit-hosts.py --host <h>` should show
  no unexpected drift.
