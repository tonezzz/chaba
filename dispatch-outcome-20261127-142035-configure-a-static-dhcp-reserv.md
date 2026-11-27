# Dispatch outcome — omen-lan-reservation (2026-11-27)

## What I found

The card's premise was half-stale: the DHCP reservation Tony chose already
existed and the wired path was already drift-proof — but a live service was
still pointing at the dead drifted IP.

- **tony-omen has two LAN attachments**: `eno1` wired on tony-home
  192.168.2.0/24 (gw 192.168.2.1, ZTE F688 ONT) and `wlo1` wifi on
  TP-Link_C4DC_5G 192.168.0.0/24 (different router, preferred default route).
- **eno1 is `ipv4.method=manual` 192.168.2.86/24** in NetworkManager — no
  DHCP on the wired path, so host-side drift is impossible (profile dates to
  ~2026-11-13).
- **Router bindings verified live** via the ZTE F688 admin API (reverse-
  engineered login + menuData token flow, now documented in
  `docs/kb/zte-f688-admin-api.md`): `tonyomen`=192.168.2.86/b0:22:7a:f0:73:cd
  and `omenwlan`=192.168.2.84/d0:57:7b:ea:6a:3c both present. DHCP pool is
  .65–.99; bindings carve the pinned IPs out. Table is FULL (10/10 entries).
- **The actual live bug**: `~/.config/systemd/user/cast-browser.service` on
  omen still had `MEDIA_BASE=http://192.168.2.84:8090` — the 2026-10-12 drift
  value. `.84` is dead on the LAN (wlo1 moved subnets), so Chromecast media
  fetches were failing. Repo already said `.86`; the fix never reached the
  live unit.
- `cast-shots-http.service` live already binds `0.0.0.0:8090` (DHCP-proof);
  the repo copy still had `--bind 192.168.2.86` — synced repo to live.
- mDNS note: avahi-daemon on omen is `allow-interfaces=wlo1` only (deliberate
  2026-08-05 fix), so `tony-omen.local` does not resolve to .86 for
  non-Tailscale LAN clients. Left unchanged — the .86 IP literal is the
  contract; revisit only if a consumer needs mDNS.

## What changed

Live (tony-omen):
- `cast-browser.service`: `MEDIA_BASE` .84→.86, daemon-reload + restart;
  verified `is-active=active`, env shows .86.

Repo (this worktree, committed on dispatch branch):
- `stacks/services/cast-browser/cast-shots-http.service` — synced to live
  (`--bind 0.0.0.0` + pkill `ExecStartPre`).
- `docs/ssot/infrastructure/ssot.ip-address-registry.yml` — .84 re-attributed
  to omen wlo1 (reservation/omenwlan), added .86 omen eno1 (static), old .86
  squatter `mac-72b5f0db14f3` marked stale.
- `docs/ssot/infrastructure/ssot.tony-omen-multi-wan.yml` — verified-live
  binding note + eno1 static/cast-stack state note.
- `docs/kb/zte-f688-admin-api.md` — NEW: ZTE F688 admin API recipe.
- `docs/ssot/jobs/infrastructure/2026-11-27-omen-lan-reservation.yml` — NEW:
  full job trail.

## Result / verification

Done-condition met: tony-omen responds reliably at its assigned LAN IP
192.168.2.86 — pinned twice (host static + router DHCP binding) — verified
from LAN peer tony-dell: `ping 192.168.2.86` OK, `http://192.168.2.86:8090/`
→ 200, cast-browser :8799 active. No router writes were needed; no manual
intervention required going forward.

Verify yourself:
- `ssh tony-dell 'curl -s -o /dev/null -w "%{http_code}" http://192.168.2.86:8090/'` → 200
- `ssh tony-omen 'systemctl --user show cast-browser -p Environment | grep MEDIA_BASE'` → .86
- Router bindings: run the recipe in `docs/kb/zte-f688-admin-api.md`.

lessons:
- Repo unit files and live `~/.config/systemd/user` units drift independently — `systemctl --user cat` the live unit before trusting repo state; the .84 MEDIA_BASE bug existed only live.
- ZTE F688 `menuData` needs the literal `_lua.lua` tag suffix plus the per-page `_sessionTmpToken` (hex-escaped in menuView HTML) as a query param, else `SessionTimeout`.
- "DHCP reservation exists" needs live verification — bindings date to 2026-09-17 yet drift still happened 2026-10-12; the host-side static NM profile was the real fix.
- Dispatch sessions on idc02 can still reach LAN hosts via tailscale SSH (`ssh tony-omen`, `ssh tony-dell`) for verification and small reversible live fixes.
