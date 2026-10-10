# ada-ha consumer audit — 2026-10-10

Question: who uses ada-ha on tony-dell; can it move to idc01/idc03?

## What it actually is

A full HA container (`homeassistant:stable`, `127.0.0.1:8125`, config at
`~/.config/ada-ha`) that outgrew its documented "dev/lab tier, no
integrations" role — the SSOT instance note is **stale**.

- **340 entities, 25 config entries, live events** (DB last event today)
- Integrations: `mobile_app` ×2 (TONY-IP + Apple Watch — live inbound),
  androidtv_remote (TONY-TV), sonoff, xiaomi_miot ×2, tuya, cozylife
  (smart plugs — LAN-local protocols), esphome, cast/dlna/go2rtc media,
  ipp (HP printer), camera feeds, album_slideshow, radio_browser
- Voice/AI experiments: gemini_live + google_generative_ai_conversation
  (**401 dead creds — flagged for cleanup**), google_translate,
  ha_mcp_tools, shopping_list
- Zero live automations (`automations.yaml: []`; ~20 `automation.*`
  registry entries are deleted-automation orphans)
- Dashboard: `chaba-nest` — the Nest/Polity/Security/Traffic/Flood
  CMS-iframe tabs + the Board tab (added by Tony 2026-10-09), pinned
  #2 in sidebar

## Who uses it

1. **TONY-IP + Apple Watch** — mobile_app feeds (battery/focus/camera/
   kiosk sensors land here)
2. **Tony via chaba-nest** — the lab dashboard, actively edited
   yesterday
3. Device entities — actuation path exists (LAN protocols) but no
   automations; control happens manually via dashboard or not at all
4. Ada voice experiments — mostly broken (gemini creds 401)

## The transport facts

- Inbound (phone/watch) — works over tailnet either way
  (`tony-dell…:8125` ↔ `idc03…:8125`, same shape)
- Outbound (LAN plugs/TV/printer) — **LAN-dependent**: tony-dell
  advertises `192.168.2.0/24` but **idc03 runs `--accept-routes=false`**
  — moving ada-ha to idc03 breaks LAN actuation unless accept-routes
  is enabled (imports dell's route — a real routing change on a prod
  edge host, deserves its own decision)

## What actually froze the dell screen

Not ada-ha — `devin-desktop` autostarted two instances; four Electron
renderers oversubscribed all 8 cores. The box's stability problem is
desktop software on a server, not this container.

## Recommendation

- **Keep ada-ha on tony-dell** — it's LAN-native; remote-host control
  of LAN devices adds a tailnet dependency to every plug flip.
- **Real fix**: disable devin-desktop autostart on tony-dell (server,
  not a workstation) — card it.
- **Cleanup inside ada-ha**: dead gemini config entries (401 spam),
  prune orphaned automation.* registry entries.
- If consolidation still wanted later: move it as the *last* dell
  resident once accept-routes on idc03 is separately decided —
  flipping accept-routes on the public edge host is a routing-policy
  decision, not a side effect of this move.

## The audit procedure (standard, reusable)

1. **SSOT role check** — what do instances/services/routes say it is?
   (Found: stale — flagged)
2. **Config truth** — configuration.yaml automations.yaml, config
   entries list, custom_components
3. **Live evidence** — entity count, DB last-event, active states;
   logbook recent activity
4. **Consumers** — inbound (mobile_app feeds, ws clients, URL users),
   outbound (device actuation, integrations it drives)
5. **Transport test** — can the target host reach what it needs?
   (subnet routes, port reachability — caught the accept-routes issue)
6. **Root-cause sanity** — is the thing being blamed actually the
   cause? (ada-ha wasn't)
7. Decide: keep / move / split — card with evidence.
