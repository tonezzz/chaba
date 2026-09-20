---
category: operations
type: runbook
---

# Media Casting Runbook (tony-omen)

How to get this machine's screen/media onto the iPad and the TVs. Deskreen was
removed 2026-09-19 — do not reinstall it; the supported paths are below.

## Paths by target

| Target | Path | Client software |
| --- | --- | --- |
| iPad (screen mirror) | Sunshine host → Moonlight | Moonlight app (App Store) |
| Samsung TV-40C5000 (`.91`/`.92`, floats) | DLNA only — no AirPlay/Screen Mirroring | built-in DMRND renderer |
| TrueID box `tony-tv` (`.85`) | Chromecast built-in | Google Home / Chrome cast |
| TrueID box AirPlay | AirScreen app on the box | iPad/iPhone AirPlay |

## Network prerequisites

- tony-omen must be on the home LAN (`192.168.2.x`). When tethered to the
  iPhone hotspot (`172.20.10.x`), none of the home devices are reachable.
- `lan-route-pref.service` must be active: Tailscale's table-52 rules otherwise
  steal the local subnet and LAN clients see replies from the wrong source IP.
  Verify: `ip rule | grep 5000` → `from all to 192.168.2.0/24 lookup main`.

## Sunshine (iPad mirroring)

Package: `sunshine_2026.906.222525-1+ubuntu26.04_amd64.deb` staged in
`~/Downloads` (LizardByte release v2026.906.222525; do not auto-bump without
checking release age).

```bash
# install + enable (single paste)
sudo apt install -y ~/Downloads/sunshine_2026.906.222525-1+ubuntu26.04_amd64.deb \
  && systemctl --user enable --now sunshine
```

- Web UI / credentials: `https://localhost:47990` (self-signed cert; set the
  admin user/pass on first visit).
- Pairing: open Moonlight on the iPad → select the host → enter the PIN shown
  into Sunshine's PIN page. Requires both devices on the same LAN.
- Verify: `systemctl --user status sunshine`, `ss -tln | grep 4799`.

## Samsung TV (DLNA)

Renderer: `DMRND/0.5`, DMR-1.50, UDN `215459bb-96b5-04f5-1476-2f50d2b694f9`,
desc `http://<ip>:52235/dmr/SamsungMRDesc.xml`. IP DHCP-floats (seen `.91`,
`.92`); NIC dies in standby, so it is only reachable while the panel is on.
Behind the Tenda repeater it appears in ARP with the repeater's WAN MAC
`0A:F0:BC:AD:20:8B` (MAC-NAT).

- Pull path (verified clean 2026-09-17): `systemctl --user start rygel`, share a
  file, on the TV use MEDIA.P/Source → pick `TonyTest`.
- Push path (`SetAVTransportURI` + `Play` to `:52235`): works, but the TV shows
  an on-screen accept prompt every time.
- Optional later step: add to HA as a `dlna_dmr` media player (ask first).

## cast-desktop pipeline (legacy, kept)

`cast-desktop@.service` + `~/.local/bin/cast-desktop-run.sh` capture an X11
display to HLS (`~/.local/share/cast-desktop/desktop/`). Disabled by default;
still the fallback for pushing a live desktop stream to a DLNA/HLS client.
Thumbnails `thumb-workspace-*.png` are used by
`~/.local/bin/switch-cast-desktop-workspace.sh` — do not delete them.

## Tenda repeater notes (`tony-repeater`)

- Universal Repeater (client+ap): upstream `TONY-WIFI_2.4G` → own SSID
  `TONY-WIFI_2.4G-ext`, 2.4GHz only, ch6/20MHz, WPA2-PSK. DHCP server OFF.
- Admin UI `http://<ip>/login.html`; own IP floats (`.72`/`.73`/`.82`) and the
  UI auto-reboots daily at 03:00 — admin pages are intermittently unreachable.
- Full config dump: `~/.local/ai-hub/page-dumps/repeater-config-2026-09-18.json`.

## References

- Device/MAC registry: `docs/ssot/infrastructure/ssot.mac-address-registry.yml`
  (`tony-tv`, `samsung-tv`, `tony-repeater` entries)
- Tailscale subnet-route conflict fix: `AGENTS.md` → "Tailscale subnet-route
  conflict"; `lan-route-pref.service`
- TV-corner power: `switch.plug_tv` feeds Samsung + TrueID + repeater — ask
  before power-cycling.
