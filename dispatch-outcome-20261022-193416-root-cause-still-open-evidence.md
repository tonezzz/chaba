# dispatch-outcome — mn-ha-v4-8123-blocked root cause

## Verdict

The :8123 drop is **not a tailnet ACL and not a bug** — it is the deliberate
`mn-ha-quarantine` Tony ordered 2026-10-16 ("don't touch anything in
Michael's house; kill the connection"), already documented in
`docs/ssot/infrastructure/ssot.home-assistant.michael.yml` but missed by the
card's hypothesis and by the session that installed the v6 workaround.

## Evidence chain

- `idc03` iptables OUTPUT, rule #1: `DROP tcp --dport 8123 -d 100.80.105.88`
  — **8,411,457 packets / 504 MB matched**, inserted above the ufw chains.
- tcpdump on **idc03** `tailscale0`: the :8123 SYN never leaves the tun
  (drop is local egress). :9584 SYN passes and handshakes normally.
- tcpdump on **michael-ha** `tailscale0` (entered via `a0d7b954_ssh` on
  :2222 through tony-omen): idc03 :9584 traffic arrives; idc02/tony-dell
  :8123 flows pass. Host iptables INPUT → `ts-input` accepts all tailnet
  traffic; the destination side is clean.
- Reachability: only idc03 fails :8123 (v4). tony-dell, mn01, idc02,
  macbook, tony-omen all connect. All other idc03→michael-ha ports fine.
- Unit: `/etc/systemd/system/mn-ha-quarantine.service` (enabled, active
  since Oct 16).

## Corollary finding — quarantine was silently defeated

The 2026-10-20 "workaround" in `idc03:~/.config/secrets/ada-ai-kraut.env`
(HOME_ASSISTANT_URL → v6 ULA literal) bypassed the v4-only rule for ~2
days — mn lane HA tools (incl. writes to Michael's plugs) worked against
the kill order. Added under a mistaken "tailnet ACL" diagnosis.

## Actions taken (all reversible)

1. Extended `mn-ha-quarantine.service`: added `ip6tables -I OUTPUT 1 -d
   fd7a:115c:a1e0::692d:6959 -p tcp --dport 8123 -j DROP` to ExecStart +
   matching ExecStop; `daemon-reload`; rule applied live. Persisted across
   reboot.
2. Reverted `ada-ai-kraut.env` → `HOME_ASSISTANT_URL=http://michael-ha:8123`
   with corrected comment (backup `ada-ai-kraut.env.bak-20261022`).
3. `systemctl --user restart ada-ai-kraut` — mn lane HA tools now fail
   closed, per the standing order.
4. SSOT updated (`ssot.home-assistant.michael.yml` quarantine section) +
   job trail `docs/ssot/jobs/home-assistant/2026-10-22-mn-ha-quarantine-rootcause.yml`,
   committed on the dispatch branch (no push).
5. Board comment with root cause; board request raised for the keep/lift
   decision (`mn-ha-quarantine-is-now-enforced-on-v4-v-16aa75`).

## Verify

- `ssh idc03 'sudo iptables -L OUTPUT -n | head -3; sudo ip6tables -L OUTPUT -n | head -3'`
  → both show the :8123 DROP to michael-ha (v4 + v6 ULA).
- `ssh idc03 'curl --connect-timeout 5 http://[fd7a:115c:a1e0::692d:6959]:8123/'`
  → timeout (was answering before).
- `ssh idc03 'bash -c "</dev/tcp/100.80.105.88/9584"'` → still open.

## If Tony answers "lift"

`ssh idc03 'sudo systemctl disable --now mn-ha-quarantine'` — removes both
rules; `ada-ai-kraut.env` already points at the canonical v4 URL. Then the
mn lane works via `http://michael-ha:8123` and this card can close.
