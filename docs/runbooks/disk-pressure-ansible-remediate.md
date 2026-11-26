---
title: Disk Pressure — Assess / Verify / Fix with Ansible
description: Standard gated procedure for disk-space incidents — dry-run first, thresholds from SSOT, rebuildable-cache-only cleanup, explicit opt-in before any mutation
tags: [ansible, disk, runbook, sop, remediation, infrastructure]
created: 2026-11-26
updated: 2026-11-26
category: operations
status: verified
last_verified: 2026-11-26
verification_method: dry-run validated on tony-macbook (Linux play) and kk-mac (macOS audit play) from origin/master worktree ops/ansible-disk-standard
scope: Linux fleet hosts via disk-remediate.yml; macOS member devices audit-only
owner: tony
related:
  [
    ansible/playbooks/disk-remediate.yml,
    ansible/playbooks/disk-headroom.yml,
    scripts/ada/disk-trend-watch.py,
    docs/kb/disk-space-management.md,
    docs/ssot/jobs/infrastructure/2026-11-26-ansible-disk-standard.yml,
  ]
search_keywords: [disk pressure, disk space, df headroom, uv cache, pip cache, journal vacuum, ansible disk-remediate, dry run, disk-headroom, disk-trend-watch]
---

# Disk Pressure — Assess / Verify / Fix with Ansible

**Abstract**: The standard way to handle a disk-space alert. `disk-headroom.yml`
already covers **assess** (df probe, reports, board alerts) and
`disk-trend-watch.py` turns trends into cards. `disk-remediate.yml` adds the
missing **verify → fix** half. It is **dry-run by default**: nothing is deleted
unless `-e disk_remediate_apply=true` is passed, a threshold is actually
breached, and an explicit `--limit` names the host.

## The three phases

| Phase | Owner | What it does |
| --- | --- | --- |
| Assess | `disk-headroom.yml` / `disk-trend-watch.py` | Probe df, write reports, raise board cards on trend |
| Verify | `disk-remediate.yml` (default) | Re-probe **live** df, resolve SSOT ceiling + 15 GiB floor, size rebuildable caches, decide `needs_fix` |
| Fix | `disk-remediate.yml` (`-e disk_remediate_apply=true`) | Purge only caches above their cap, then re-probe; escalate to a human if still over |

**Verify the current `df` before acting on a trend card** — a "critical" card
may have self-healed while the watcher was unable to probe the host. This is
exactly what happened with `disk-auto-macbook-root` and
`disk-auto-kk-mac-System-Volumes-Data` on 2026-11-26.

## Thresholds

- Root usage ceiling: per-host `expected_resources.max_root_disk_percent` from
  `docs/ssot/infrastructure/ssot.audit.hosts.yml`, default **90%**.
- Absolute floor: **15 GiB** available on `/` (matches the `mddb-backup` guard).
- `needs_fix` is true when **either** threshold is breached.

## Safe cleanup candidates (Linux only)

| Target | Cap | Action |
| --- | --- | --- |
| `~/.cache/uv` | 8 GiB | `uv cache clean` (rebuildable via `uv sync` / `uv pip install`) |
| `~/.cache/pip` | 1 GiB | `python3 -m pip cache purge` |
| `/var/log` (journal) | 2 GiB | `journalctl --vacuum-size=500M` |

Never user documents. Never personal caches on macOS member devices. If
cleanup does not bring the host under threshold, **escalate to the owner** —
this playbook deliberately has no destructive fallback.

## Procedure

Run from `chaba/ansible/` with the repo vault password exported:

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=~/.ansible/vault-pass.txt
```

### 1. Verify (always do this first, read-only)

```bash
ansible-playbook -i inventory/hosts.yml playbooks/disk-remediate.yml \
  --check --diff --limit tony-macbook
```

Read the `Report assessment` line: `root=…% avail=…GiB ceiling=…% floor=…GiB
needs_fix=…`. `changed=0` everywhere confirms a true dry run.

### 2. Fix (only if `needs_fix=true` and the host is in scope)

```bash
ansible-playbook -i inventory/hosts.yml playbooks/disk-remediate.yml \
  --limit tony-macbook -e disk_remediate_apply=true
```

`--limit` is **mandatory** when applying; the play fails fast otherwise. To be
extra conservative, add `--skip-tags fix`.

### 3. Confirm

The play re-probes `/` after cleanup. Independently confirm:

```bash
ssh tony-macbook 'df -h /'
```

Then close or update the triggering board card with the before/after evidence.

## macOS member devices (kk-mac)

The second play is **audit-only** — it probes
`/System/Volumes/Data` and reports headroom, with `become: false` and no fix
tasks. Do not add cleanup for these hosts without owner sign-off.

kk-mac's inventory entry carries an explicit
`ansible_ssh_private_key_file: ~/.ssh/id_ed25519_opencode`. This is required
because Ansible connects to the Tailscale IP directly, so the `Host kk-mac`
alias in `~/.ssh/config` is never consulted. The global `become = True` in
`ansible.cfg` is overridden per play, so no sudo password is needed.

## Known gaps

- `disk-trend-watch.py` still resolves user `tony` against kk-mac's IP while
  inventory expects `kkkakk` + the opencode key, so its kk-mac history has
  only unreachable samples and cards can go stale. Use the playbook's live
  probe as the authority until the watcher is fixed.
- The df probe reads `/` only on Linux; `/data` (Docker/HF cache) is covered
  by `docs/kb/disk-space-management.md` and `disk-headroom.yml` separately.

## Rollback

All cleanup targets are rebuildable caches — no byte-for-byte restore, but no
user data loss. Repopulate with the project's normal install/build step. The
playbook changes are a new file plus one inventory line; revert them with git.

## Validation history (2026-11-26)

- `ansible-playbook … --check --limit tony-macbook` → `root=62% avail=83.3GiB
  needs_fix=False`, no changes.
- `--limit idc02,con01` → `74% / 77.3GiB` and `60% / 118.5GiB`, SSOT ceiling
  resolved, no changes.
- `--limit kk-mac` → `86% / 62 GiB` on the data volume, audit-only, reachable.
