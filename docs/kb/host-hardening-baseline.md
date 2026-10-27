# Host Hardening Baseline — fleet standard

Codified 2026-10-22 from the live idc02 implementation (the reference host).
Companion to `docs/kb/new-host-onboarding.md` (full provisioning flow) — this
doc is the *security postures only* checklist, used both for new hosts and for
auditing existing ones. Per-host listener inventories live in
`docs/ssot/infrastructure/ssot.security.<host>.yml` — this doc is the shared
layer those files extend.

## Host classes

| Class | Hosts | Exposure |
|---|---|---|
| `public-vps` | idc02, idc03, con01 (idc01†) | public IP — hostile inbound 24/7 |
| `home-lan` | tony-dell, tony-omen, mn01 | LAN behind NAT; LAN services need LAN ports |
| `workstation` | tony-macbook, kk-mac | laptop/desktop; tailnet + occasional LAN |

† idc01: offline since ~2026-10-21 (contract lapse) — baseline moot unless revived.

## A. Common (all hosts)

| # | Check | Verify | Apply |
|---|---|---|---|
| A1 | sshd: password auth OFF, root key-only via dropins | `sshd -T \| grep -E "passwordauthentication\|permitrootlogin"` → `no` / `prohibit-password` | dropins `/etc/ssh/sshd_config.d/00-no-password.conf` (`PasswordAuthentication no`) + `20-root.conf` (`PermitRootLogin prohibit-password`) — do NOT edit stock sshd_config |
| A2 | `loginctl enable-linger tony` on any host running user services | `loginctl show-user tony -p Linger` → `yes` | `sudo loginctl enable-linger tony` |
| A3 | `unattended-upgrades` enabled | `systemctl is-enabled unattended-upgrades` | `sudo apt install unattended-upgrades` |
| A4 | `/etc/sysctl.d/90-tuning.conf` (verbatim below) | `sysctl net.ipv4.tcp_congestion_control` → `bbr` | write file + `sudo sysctl --system` |
| A5 | tailscale up, own node identity | `tailscale status` | per onboarding doc; never reuse a stick identity |
| A6 | `~/.ssh/authorized_keys` = fleet key set; `known_hosts` populated | `ssh -o BatchMode=yes <peer> hostname` | per onboarding §2 (ssh-mesh-sync maintains it) |
| A7 | `~/.config/secrets` mode 700, secret env files 600 | `stat -c %a` | per `ssot.secrets.policy.yml` — only what the role needs |
| A8 | podman + subuid/subgid where containers run | `podman --version`; `grep tony /etc/subuid` | `sudo apt install podman uidmap` |
| A9 | no stray public listeners — `ss -tlnp` matches `ssot.security.<host>.yml` | `ss -tlnp \| grep 0.0.0.0` | mask/stop or register the listener in the SSOT file |

`/etc/sysctl.d/90-tuning.conf` (from idc02):

```
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
vm.swappiness = 10
fs.inotify.max_user_watches = 524288
net.core.somaxconn = 8192
net.ipv4.tcp_max_syn_backlog = 8192
```

## B. public-vps (idc02/idc03/con01)

| # | Check | Verify | Apply |
|---|---|---|---|
| B1 | ufw: deny-in default, allow-out, routed disabled | `sudo ufw status verbose` | `ufw default deny incoming; ufw default allow outgoing; ufw default deny routed` |
| B2 | ufw rules: `tailscale0 ALLOW` + explicit public ports only | rule list = tailscale0-any + 80/443 (edges) | `ufw allow in on tailscale0`; `ufw allow 80,443/tcp` — **no public :22**; ssh arrives via tailnet only |
| B3 | ufw active + logging low | `Status: active`, `Logging: on (low)` | `ufw logging low; ufw enable` |
| B4 | fail2ban active (covers any public auth surface) | `systemctl is-active fail2ban` | `apt install fail2ban` — stock `defaults-debian` jail suffices |
| B5 | qemu-guest-agent active | `systemctl is-active qemu-guest-agent` | `apt install qemu-guest-agent` |
| B6 | masked/retired units stay masked | `systemctl is-enabled <masked unit>` → `masked` | `systemctl --user mask <unit>` (split-brain guard — e.g. old mddb leaders) |

Public listeners per host live in `ssot.security.<host>.yml` — ufw rules must
match that file, not this doc.

## C. home-lan (tony-dell, tony-omen, mn01)

LAN hosts legitimately serve the LAN (HA :8123, go2rtc :1984, frigate, VMS/VNC,
SSH for local admin). The rule is *no unintended listeners*, not "close
everything" — a blind `ufw deny-in` breaks the house.

| # | Check | Verify | Apply |
|---|---|---|---|
| C1 | listener inventory matches `ssot.security.<host>.yml` | `ss -tlnp` vs file | register or kill strays — audit, don't auto-fix |
| C2 | sshd reachable on LAN + tailnet, key-only (A1) | same as A1 | same dropins |
| C3 | no ports forwarded/exposed on the router | router check (Tony) | — |
| C4 | tailscale up + funnel/serve ACLs minimal | `tailscale status`, `tailscale serve status` | remove stale serve/funnel entries |
| C5 | ufw either inactive OR LAN-scoped allow-list — never half-configured | `ufw status` | if enabling: allow LAN CIDR + tailscale0 + explicit service ports first |

Policy settled 2026-10-27 (`docs/ssot/jobs/infrastructure/2026-10-27-lan-class-f2b-qemu-decision.yml`):

- **fail2ban: enabled** on home-lan hosts as a tripwire — `jail.local` MUST set `ignoreip` covering loopback + RFC1918 + `100.64.0.0/10` (tailnet) so local sources can never self-lockout; only non-local sources reaching sshd are bannable.
- **qemu-guest-agent: n/a on bare metal** — check `systemd-detect-virt`; declare a `{item, reason, last_verified}` deviation in `ssot.security.<host>.yml` instead of installing.

## D. workstation (tony-macbook, kk-mac)

| # | Check | Verify | Apply |
|---|---|---|---|
| D1 | sshd key-only (A1); tailnet reach | `ssh macbook` works from fleet | same dropins |
| D2 | ufw deny-in + tailscale0 allowed (laptop = untrusted networks) | `ufw status` | `ufw default deny incoming; ufw allow in on tailscale0; ufw enable` |
| D3 | linger only if the laptop runs user services | `loginctl -p Linger` | macbook: yes (runs jobs) |

## Audit procedure

0. **Sequencing on fresh hosts (learned 2026-10-22 con01):** join tailscale and
   confirm tailnet ssh **before** `ufw enable` — enabling ufw first locks you
   out when public `:22` was your only path in. Recovery then needs provider
   VNC/console to run `tailscale up` by hand.
1. Read-only checks (A + class section) per host — script the verify column,
   don't eyeball.
2. Apply class-A fixes freely (dropins, linger, sysctl, fail2ban install) —
   they're additive and reversible.
3. ufw changes on `home-lan` = report-first, not auto-apply (LAN breakage risk);
   on `public-vps` safe to apply if rules match the security SSOT file.
4. Record results on the relevant card + update `ssot.security.<host>.yml`
   when a real listener delta is found.

## Related

- `docs/kb/new-host-onboarding.md` — full provisioning flow (this doc is §1's
  security slice expanded)
- `docs/ssot/infrastructure/ssot.security.*.yml` — per-host listener inventories
- `scripts/security-audit.sh`, `scripts/audit-security.py` — repo-side audits
- `scripts/audit-hosts.py` — fleet expected-services audit
