# Ansible fleet notes

Run from this control host over SSH keys. No `--ask-become-pass` needed.

```bash
cd ~/ansible
ansible-playbook -i inventory.ini system-update.yml
ansible-playbook -i inventory.ini system-update.yml --limit macbook
ansible-playbook -i inventory.ini system-update.yml --limit omen
ansible-playbook -i inventory.ini wifi-fix.yml --limit macbook
ansible-playbook -i inventory.ini opencode-update.yml
```

## OpenCode CLI updates

`opencode-update.yml` targets the `[opencode]` group and upgrades the CLI to a
pinned version (currently `2.4.1`). Install methods differ per host, so each has
a `host_vars/<host>.yml` declaring `opencode_method`, `opencode_bin`, and where
needed `opencode_npm_sudo` (idc02's npm prefix is root-owned) or
`opencode_remove_v1` (omen was on the V1 `opencode-ai` package and needed a
package swap, not an upgrade). The task asserts the active version afterwards.

Upgraded 2026-11-24: idc02 (the control host) and omen were brought to 2.4.1;
idc02 had two installs — a stale curl binary in PATH shadowing the npm global —
and both are now tracked in `host_vars/idc02.yml`. omen needed a V1 → V2 package
swap, dell was already current. The serve rollout gave MacBook, con01 and idc03
the pinned binary at `~/.opencode/bin/opencode`; they were added to `[opencode]`
afterwards so one run keeps all six installations aligned. Verified idempotent —
re-runs report `changed=0` everywhere.

Note: npm global bin directories are exported in interactive shells only (Ubuntu
`.bashrc` returns early for non-interactive shells), so `command -v opencode`
can be empty over SSH. The playbook uses absolute `opencode_bin` paths.

**The Ansible control host is idc02** (same hostname, Tailscale IP
`100.123.163.11`, and `/etc/machine-id`). There is deliberately no separate
`control` inventory entry — listing both would double-target the same machine
and risk concurrent apt locks. idc02 has two OpenCode installs: a root-owned npm
global (`/usr/local/bin/opencode`) and a user curl binary first in PATH
(`~/.opencode/bin/opencode`); both are covered by `host_vars/idc02.yml` and the
playbook asserts both are at the target version.

## OpenChamber

OpenChamber is the web UI for OpenCode and is installed only on the control
host (idc02), via npm global `@openchamber/web` at `/home/tony/.local/node`.
Updated 2026-11-24 from 2.7.3 to **2.8.0** using `openchamber update`; the
systemd user service `openchamber.service` auto-restarted and is active on
port 3000 with startup enabled.

Related versions checked the same day: `@opencode/cli` 2.4.1 (satisfies
OpenChamber's `opencode >=2.2.4` engine), Node 24.14.0 runs the server (satisfies
`node >=24.14.0`), though PATH `node` is still 22.22.1. `npm` (10.9.4 → 12.2.3)
and `corepack` (0.34.6 → 0.36.0) are outdated but are general Node tooling, not
OpenChamber dependencies; left alone deliberately.

## Retired containerized servers (2026-11-24)

`ada-code`, `ada-code-enroll`, `jack-opencode` and `jack-enroll` were retired in
favour of ada-ocb. Services stopped and disabled, quadlet files renamed with a
`.retired-20261124` suffix, containers and four images removed. Data and secrets
were **moved** to `~/backups/retired-opencode-20261124/` (not deleted) so they
can be restored or purged later.

**Tidy-up done:** the three stale `reverse_proxy` routes for
`opencode-jack`, `ada-code` and `opencode-ada` (ports 8377/8378) were removed
from `~/.config/caddy/Caddyfile`, validated with `caddy validate` and reloaded.
Backup: `Caddyfile.bak-retired-opencode-20261124`.

## OpenCode serve / workload delegation

`opencode-serve.yml` deploys an authenticated `opencode-serve.service` from
`roles/opencode_serve/` to **all six hosts**, bound to each Tailscale IP on
port 4096. Enabled, idempotent (`changed=0` on re-run), with 401 for
unauthenticated `/api/*` requests and 200 with basic auth.

**Auth:** the v2 host CLI generates a random password at each start. Setting
`OPENCODE_PASSWORD` and `OPENCODE_SERVER_PASSWORD` in a 0600 EnvironmentFile
pins it to a shared 64-hex secret from
`~/.config/secrets/opencode-serve.password` on the controller. The earlier
concern that these variables are ignored was based on probing `/global/health`,
which is public by design — `/api/info` is the real auth check.

**No Node bootstrap needed:** `@opencode/cli` v2.4.1 ships a self-contained
275 MB ELF binary. The role downloads the pinned GitHub release to
`~/.opencode/bin/opencode` on hosts that lack it (macbook, con01, idc03).
Each host gets a serve-only config at `~/.config/opencode-serve/opencode.json`
(pointing at the LiteLLM proxy on idc03, using `LITELLM_KEY` from
`~/.config/secrets/litellm-ada.env`), so local interactive configs are untouched.

**Verification:** created a session on con01 and sent a prompt through the API;
the assistant replied `PONG` using `litellm/gemini-3.5-flash-lite`. The helper
`./opencode-delegate.sh <host> <prompt...>` automates this; host IPs are in
`serve-hosts.txt`.

## Tailscale ACLs (2026-11-24)

`tailscale-acl.hujson` is the source of truth for tailnet `taila0626a.ts.net`.
It replaced the stock allow-all policy with two grants:

1. controller `100.123.163.11` (idc02) → any host, `tcp:4096`
2. everyone → any host, ports `1-4095` and `4097-65535` (everything except 4096)

Grants are additive and have no deny action, so the broad rule enumerates the
port ranges around 4096. SSH (`autogroup:member` → `autogroup:self`) and the
Funnel node attribute from the default policy are preserved. The policy
includes built-in tests (controller allowed, other host denied, SSH allowed)
which Tailscale validates on save.

Applied via `POST https://api.tailscale.com/api/v2/tailnet/taila0626a.ts.net/acl`
with `Content-Type: application/hujson` and `If-Match` set to the ETag from a
fresh `GET /acl` (it was *not* the literal `ts-default` hash). No token is
stored in this repo; the API token was supplied through the private secret
card. Verified after rollout: `curl` to `con01:4096` returns 200 from idc02 and
fails from omen, while SSH from omen to con01 still works.

## Privilege model

Playbooks use `become: false` with explicit `sudo <absolute-binary>` calls, so the
sudoers rules are scoped to exact binaries and argument lists rather than full root.

- MacBook: `/etc/sudoers.d/ansible-macbook` (driver repair),
  `/etc/sudoers.d/ansible-apt` (package maintenance),
  `/etc/sudoers.d/ansible-reboot` (reboot only).
  Verified 2026-11-23: both playbooks still run green, every permitted `tee`
  path is authorized, and arbitrary argument variants (e.g. `apt-get --version`,
  `modprobe -n`, `nmcli connection show`) are denied.
- Omen and Dell already have passwordless sudo configured on the machines.
- con01 and the IDC hosts have unrestricted passwordless sudo, so they use
  non-interactive conffile flags (`--force-confdef`, `--force-confold`) via
  `host_vars/con01.yml` and `group_vars/idc.yml`. Desktops keep the exact
  command their scoped sudoers rules expect.

## MacBook WiFi repair

The BCM43602 probes before `brcmfmac_wcc` is available at boot, so the kernel
logs `mod=wcc: failed 256` and the device ends up disabled. Two layers fix it:

1. `/etc/modules-load.d/brcmfmac-wcc.conf` persists the plugin.
2. `brcm-wifi-reprobe.service` runs after `systemd-modules-load` and
   `NetworkManager`, re-probing the PCI device and bringing `wlp3s0` up.

Verified across a cold reboot on 2026-11-23.

## Update playbook

`system-update.yml` does: refresh apt lists, report upgradable packages,
`apt-get -y upgrade`, `--only-upgrade install devin-desktop`,
`apt-get -y autoremove`, `apt-get autoclean`, then prints a before/after summary.
Reboots are deliberately a separate decision, never folded into the playbook.

## Home Assistant plug control

`playbooks/homeassistant-plug.yml` reads or switches a Home Assistant switch
(smart plug) through the HA REST API. It targets `omen`, where the request
originates on `http://127.0.0.1:8123/api` — no Tailscale/HTTPS exposure of the
API is needed. The long-lived token is read at run time from the private file
`/home/tony/.config/secrets/home-assistant-token.env` on omen; no token is kept
in this repo. Both the pre- and post-state are fetched and asserted.

```bash
cd ~/ansible
ansible-playbook -i inventory.ini playbooks/homeassistant-plug.yml
ansible-playbook -i inventory.ini playbooks/homeassistant-plug.yml -e plug_action=turn_off
ansible-playbook -i inventory.ini playbooks/homeassistant-plug.yml -e plug_action=turn_on
ansible-playbook -i inventory.ini playbooks/homeassistant-plug.yml -e plug_entity=switch.plug_tv -e plug_action=turn_off
```

`plug_action` defaults to `status` (read-only); `switch.mac_plug` is the default
entity. Verified on 2026-11-26: status, turn_on and turn_off all pass their
assertions. There is no dedicated Ansible module for Home Assistant in the
installed collections, hence `ansible.builtin.uri`.

## Runbook layout

```
~/ansible/
  README.md                 this document (runbook index + fleet state)
  inventory.ini             host groups: [idc], [opencode], [opencode_serve]; per-host vars elsewhere
  group_vars/idc.yml        shared vars for IDC hosts (apt conffile flags)
  host_vars/<host>.yml      per-host exceptions (install method, sudo, reboot rules)
  system-update.yml         apt maintenance, hosts: all
  wifi-fix.yml              MacBook WiFi repair, hosts: macbook
  opencode-update.yml       OpenCode CLI upgrade, hosts: opencode
  opencode-serve.yml        deploy opencode API servers, hosts: opencode_serve
  playbooks/homeassistant-plug.yml  HA switch on/off/status via REST API, hosts: omen
  roles/opencode_serve/     CLI install, auth env, systemd unit, health checks
  opencode-delegate.sh      send a prompt to a serve host and print the reply
  serve-hosts.txt           name -> Tailscale IP map for the helper
  tailscale-acl.hujson      tailnet policy: TCP/4096 only from controller idc02
  sudoers/                  reference copies of the scoped MacBook sudoers rules
```

Everything is committed to a local git repo (`git log` shows the maintenance
history), so each runbook change is reviewable and reversible. Hosts are grouped
by role rather than listed in playbooks; playbooks target a group or use
`--limit`. Per-host differences live in `host_vars`, never as inline `when`
clauses on hostnames. Ansible runs targeted hosts in parallel by default.

## Hosts

| Host | Role | Kernel | Devin Desktop |
|---|---|---|---|
| macbook | laptop | 7.0.0-44-generic | 3.14.30833-1795195328 |
| omen | desktop | 7.0.0-44-generic | 3.14.30833-1795195328 |
| dell | desktop | 7.0.0-22-generic | 3.14.30833-1795195328 |
| con01 | KVM server | 6.8.0-151-generic | not installed (Devin task skipped) |
| idc03 | KVM server | 6.8.0-151-generic | not installed (Devin task skipped) |
| idc02 | KVM server (control host) | 6.8.0-151-generic | not installed (Devin task skipped) |

con01 was updated and rebooted twice on 2026-11-23: 27 upgrades, then a
`dist-upgrade` for the 6.8.0-151 kernel meta-packages (6 new kernel packages,
0 removals) plus autoremove of the old 6.8.0-139 packages. Reboot flag cleared,
0 upgradable, ssh/tailscaled/fail2ban/netdata/systemd-networkd all active.
Note: `apt-get upgrade` alone will not install new kernel packages — use
`dist-upgrade` when meta-packages point at a newer kernel.

idc03 updated 2026-11-23: 50 apt upgrades, then `dist-upgrade` for the kernel
meta-packages + fwupd (5 upgraded, 7 new, 0 removed), rebooted to 6.8.0-151.
idc02 onboarded 2026-11-24 (our SSH key added as `tony`) and updated: 189
upgrades ran before a parallel run was cancelled control-side, leaving
`apt-get -y upgrade` hung at the `/etc/cloud/cloud.cfg` conffile prompt for
13 hours. Recovered by killing PIDs 3450630/3457307, running
`dpkg --configure -a --force-confold`, then finishing the remaining upgrades,
`dist-upgrade` (5 upgraded, 7 new, 0 removed), autoremove and reboot.
Both IDC hosts end at 6.8.0-151, 0 upgradable, reboot flag cleared, with
ssh/tailscaled/fail2ban/netdata/networkd/unattended-upgrades active. idc02's
22 rootless podman containers (mddb-ops, weaviate, caddy-edge, etc.) came back.

**Conffile trap:** `-y` does not answer dpkg conffile questions. If the SSH
session dies while a prompt is open, dpkg blocks forever holding the apt locks.
Use `--force-confdef --force-confold` (keeps local config) on hosts whose sudo
allows extra arguments; never leave a headless apt run without them.

A fleet-wide `system-update.yml` pass on 2026-11-24 cleared the follow-up
security updates (Chrome, libssh, python3-oauthlib, tzdata) on all six hosts:
0 upgradable everywhere, no reboot flags, 0 failures. The hardened conffile
flags worked on every server with no prompts.

Parallelism: Ansible runs all targeted hosts concurrently (default 5 forks,
`-f N` to change). Use the `[idc]` group and `serial` for rolling rollouts.
