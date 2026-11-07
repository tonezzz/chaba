# Dispatch outcome — host-hardening-residuals (2026-10-27)

## What was done

**LAN-class half of the card — resolved and applied:**

- **fail2ban → enabled** on tony-omen and mn01 (decision: enable, not
  exception — baseline audit procedure lists f2b install among apply-freely
  fixes, and enabled-as-tripwire covers any future non-local sshd exposure).
  Installed fail2ban 1.1.0 + `/etc/fail2ban/jail.local` with
  `ignoreip = 127.0.0.1/8 ::1 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16
  100.64.0.0/10` so LAN/tailnet sources can never self-lockout (matters on
  mn01: tailnet-only reach, no OOB console). Verified `fail2ban-client
  status sshd` active with ignoreip loaded on both hosts.
- **qemu-guest-agent → declared exception** on both: `systemd-detect-virt`
  = none (tony-omen = bare-metal HP 15-BC, mn01 = bare-metal FUJITSU
  ESPRIMO Q556/2). Recorded as `{item, reason, last_verified}` deviations
  in `ssot.security.tony-omen.yml` / `ssot.security.mn01.yml` (con01
  format), plus `baseline_applied` entries for f2b.
- Policy written into `docs/kb/host-hardening-baseline.md` §C and full
  rationale in `docs/ssot/jobs/infrastructure/2026-10-27-lan-class-f2b-qemu-decision.yml`.

**Macbook half — blocked on sudo, packaged for Tony:**

- Verified live: stock sshd (no `sshd_config.d` dropins;
  `PasswordAuthentication` unset → default **yes**; `Include
  /etc/ssh/sshd_config.d/*.conf` present so dropins will take effect), no
  `/etc/sysctl.d/90-tuning.conf` (cubic, swappiness=60), Linger already
  yes, ufw unit enabled but rules unverifiable without root. This session
  has no passwordless sudo on tony-macbook, so nothing could be applied.
- One paste-block (sshd dropins + sysctl file + `sysctl --system` +
  `sshd -t && reload ssh` + verify lines incl. `ufw status verbose` for
  the D2 check) posted to the card comms and a board request raised for
  Tony to run it — request_id `run-the-sshd-sysctl-paste-block-in-the-c-bb73ed`.
- `ssot.security.tony-macbook.yml`: `password_auth` needs-verification →
  `"yes"` with verification note.

## Verify

```
ssh tony-omen 'sudo fail2ban-client status sshd'    # jail up
ssh mn01 'systemctl is-active fail2ban'             # active
# after Tony runs the paste-block on tony-macbook:
ssh macbook 'sudo sshd -T | grep passwordauthentication'  # → no
ssh macbook 'sysctl net.ipv4.tcp_congestion_control'      # → bbr
```

## Result

LAN-class items fully resolved (f2b live on both hosts, qemu-agent
declared n/a, policy + SSOT recorded). Macbook items reduced to a single
paste-block awaiting Tony via open board request — card should stay open
until that lands, then can be verified + closed.
