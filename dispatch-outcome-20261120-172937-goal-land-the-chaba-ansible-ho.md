# Dispatch outcome — ansible-host-baseline-scaffold

## What changed

Created `ansible/` scaffold verbatim per card spec (8 files):

- `ansible/ansible.cfg`
- `ansible/inventory/hosts.yml`
- `ansible/group_vars/all.yml`
- `ansible/host_vars/{tony-omen,idc02,idc03}.yml`
- `ansible/playbooks/site.yml`
- `ansible/README.md`

Plus ONE additive fix (no spec'd file modified): symlinks
`ansible/inventory/group_vars -> ../group_vars` and
`ansible/inventory/host_vars -> ../host_vars`.

## Why the symlinks

Ansible auto-loads `group_vars/`/`host_vars/` only from the **inventory
directory** and the **playbook directory**. With both nested
(`inventory/hosts.yml`, `playbooks/site.yml`), the spec'd
`ansible/group_vars` + `ansible/host_vars` are never on the playbook load
path — `ansible-playbook playbooks/site.yml` fails with
`'common_packages' is undefined` for every host. (Ad-hoc commands DO see
the vars because their basedir is the cwd.) The symlinks put the spec'd
dirs on the inventory load path without altering any file. Alternative
fix for review: physically move `group_vars`/`host_vars` under
`inventory/`.

## Verification (dry-run only, no real apply)

Controller: tony-macbook. `ansible-core 2.22.0` installed via
`uv tool install ansible-core` (no sudo/pipx on this host);
`community.general 14.0.1` installed to `/tmp/ansible-collections` for the
run (env `ANSIBLE_COLLECTIONS_PATH=/tmp/ansible-collections`).

### `ansible baseline -m ping` — all 4 baseline hosts OK

| host       | result |
|------------|--------|
| tony-omen  | pong   |
| tony-dell  | pong   |
| idc02      | pong   |
| idc03      | pong   |

tony-omen initially failed host-key verification: known_hosts had hashed
`tony-omen` entries but nothing for its Tailscale IP `100.75.102.88`.
Verified the IP's keyscan keys were byte-identical to the trusted hashed
entries, then added them. Note for future controllers: since
`ansible_host` uses IPs, each controller needs the IP (not just the ssh
alias) in known_hosts.

### `ansible-playbook playbooks/site.yml --check --diff` (with symlinks)

| host      | ok | changed | skipped | detail |
|-----------|----|---------|---------|--------|
| tony-omen | 5  | 2       | 2       | pkgs ok; 52chaba file new; u-u already enabled |
| tony-dell | 5  | 2       | 2       | same |
| idc02     | 5  | 3       | 2       | + `unzip` install; 52chaba file new |
| idc03     | 5  | 3       | 2       | + `unzip` install; 52chaba file new |

Changes are exactly the declared scope: common package installs,
`/etc/apt/apt.conf.d/52chaba-unattended-upgrades` (new on all 4),
unattended-upgrades service (already enabled everywhere), handler
restart queued by the new file. No firewall/service/distro changes.
Caveat: docker presence tasks skip in `--check` (command module), so the
docker gate wasn't exercised on omen/idc02/idc03.

### Second scaffold issue (flagged, NOT fixed — cfg kept verbatim)

`stdout_callback = yaml` in ansible.cfg **hard-errors** on
ansible-core 2.22 + community.general ≥12: "The 'community.general.yaml'
callback plugin has been removed … superseded by result_format=yaml
in ansible.builtin.default". Worked around for verification via
`ANSIBLE_STDOUT_CALLBACK=default` (the cfg's `result_format = yaml`
still gives YAML-formatted results). On distro-packaged ansible
(Ubuntu 24.04 apt → core 2.16 + community.general 9.x) the line still
works. Recommend dropping the `stdout_callback = yaml` line in a
follow-up so the scaffold works on both old and new controllers.

### Sanity

- `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ansible/**/*.yml',recursive=True)]"` → OK.
- `ansible-inventory --graph baseline` → tony-omen, tony-dell, idc02, idc03 (portable/macos/disabled correctly excluded).

## How to verify

```bash
cd ansible
ansible baseline -m ping                                  # 4x pong
ansible-playbook playbooks/site.yml --check --diff        # recap: changed=2-3/host, failed=0
```

On controllers with community.general ≥12, prefix with
`ANSIBLE_STDOUT_CALLBACK=default` until the cfg line is dropped.

## Skipped / not done

- No real apply (per card constraint).
- kk-mac, tony-macbook, mn01, idc01 intentionally not pinged (outside
  `baseline` group by design).

lessons:
- ansible only auto-loads group_vars/host_vars from the inventory dir or the playbook dir — a flat `ansible/` root with nested inventory/ and playbooks/ silently leaves all vars undefined at playbook time.
- `stdout_callback = yaml` is removed in community.general >=12; on ansible-core 2.13+ use `result_format = yaml` with the default callback instead.
- tony-macbook has no sudo/pipx/pip for dispatch sessions; `uv tool install ansible-core` + `ansible-galaxy collection install -p /tmp/...` is the working path.
- ansible_host as Tailscale IP means each controller needs the IP itself in ~/.ssh/known_hosts (hashed hostname entries don't match).
- command/shell tasks skip under --check, so `failed_when`/`when: x.rc` gates can't be exercised in dry-run.
