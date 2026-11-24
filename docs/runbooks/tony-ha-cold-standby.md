---
title: tony-ha cold standby — config sync + promotion
description: Keep a promotable cold copy of the prod tony-ha config on a standby host, and the exact steps to bring it live when tony-omen is down.
tags: [home-assistant, tony-ha, cold-standby, disaster-recovery, runbook, rsync, podman]
created: 2026-11-24
updated: 2026-11-24
category: operations
status: partial
last_verified: 2026-11-24
verification_method: >-
  Every path, host, unit name, and consumer reference below was verified
  against repo SSOT (ssot.home-assistant.instances.yml, ssot.routes.yml,
  ssot.jobs.yml, ssot.values.yml), stacks/ quadlets and caddy files, and the
  2026-10-19/20 dell→omen evacuation record in docs/kb/host-migration-tony-dell.md.
  The sync script parses and dry-runs clean; neither the sync timer nor a
  promotion has been exercised live yet — first install is the verification.
scope: >-
  tony-ha (prod instance, currently on tony-omen). Covers the config mirror,
  the promote procedure, consumer repointing, and fail-back. ada-ha shares
  the failure domain and the same pattern (noted, not duplicated). michael-ha
  (Nabu Casa) and kk-ha (idc03) are out of scope.
owner: tony
related:
  - docs/ssot/infrastructure/ssot.home-assistant.instances.yml
  - docs/ssot/infrastructure/ssot.home-assistant.tony.yml
  - docs/ssot/infrastructure/ssot.jobs.yml
  - docs/ssot/infrastructure/ssot.routes.yml
  - docs/ssot/infrastructure/ssot.audit.hosts.yml
  - docs/ssot/ssot.runbooks.yml
  - docs/ssot/jobs/home-assistant/2026-10-26-tony-ha-prod-placement-decision.yml
  - docs/kb/host-migration-tony-dell.md
  - docs/kb/host-hygiene-rules.md
  - stacks/tony-dell/tony-ha/tony-ha.container
  - stacks/idc02/tailnet-front.caddy
  - scripts/home-assistant/ha-standby-sync.sh
---

# tony-ha cold standby — config sync + promotion

Card: `tony-ha-cold-standby-config-sync-promote-d12293` (HOM-0855).
Pain being answered: omen maintenance = tony-ha fully down (demonstrated
2026-10-25); the idc02 shadow front 502s because it proxies the dead backend.
This is a **cold** standby — config mirror + documented promote, not
active-passive HA (explicitly rejected in the migration runbook: "Full HA
(active-active, keepalived, pacemaker) = too complex/risky for this fleet").

## Verified topology (do not re-derive)

| Fact | Value | Source |
|---|---|---|
| Prod instance | `tony-ha`, role `prod`, host `tony_omen` | ssot.home-assistant.instances.yml |
| Runtime | rootless podman, `Network=host`, container `tony-ha` | same |
| Image | `docker.io/homeassistant/home-assistant:stable` — **floating tag; pin by digest at promote** (patch mounts are version-pinned, see below) | stacks/tony-dell/tony-ha/tony-ha.container |
| Config | `/home/tony/.config/home-assistant` on omen (a git repo — `ha-config-backup.timer` 03:30 snapshot-commits it, **local-only**) | ssot.jobs.yml `ha-config-backup` |
| Bind/expose | `127.0.0.1:8123` in-container host-net; omen `tailscale serve` → `https://tony-omen.taila0626a.ts.net:8123` | instances.yml url block |
| Stable fronts | tailnet shadow `http://idc02.taila0626a.ts.net:8123` (stacks/idc02/tailnet-front.caddy `:8123` block → omen); public `https://tony-ha.surf-thailand.com` (idc02 edge, CF Access app 70aa9fe3) | tailnet-front.caddy, ssot.system-map.yml |
| Secrets | lane secrets already host-independent: `idc03:~/.config/secrets/tony-ha/` (backend.env, keys.json). HA-native `secrets.yaml` + `household.yml` live **inside** the config dir → they sync with the tree. No extra secret step. | instances.yml `secrets:` block |
| Existing backups | nightly local git snapshot (omen only); one-time verified MN01 copy `~/backups/omen-partition-preflight-20261025` (2026-10-25, config + consistent SQLite snapshots for tony-ha AND ada-ha — not recurring) | omen-maintenance card comms |
| Inted pull direction | ssot.jobs.yml note on `ha-config-backup`: "host-bound until moved to an idc02 remote pull" — this runbook implements that pull, on whichever standby host is chosen | ssot.jobs.yml |

Companion instance on the same host (same failure domain, optional
second target): `ada-ha` — podman network (not host), `127.0.0.1:8125`,
config `/home/tony/.config/ada-ha`, quadlet
`stacks/tony-dell/ada-ha/ada-ha.container`, idc02 shadow `:8125`.

## Standby host choice

The sync/promote machinery is host-parameterized; pick once, then declare.

| Candidate | LAN devices? | Verdict |
|---|---|---|
| **mn01** (`100.106.196.22`) | **Yes** — verified on 192.168.2.0/24, reaches LAN devices directly (2026-10-26 placement research) | **Recommended.** Promotion preserves cast/RTSP/esphome/LAN-plug control. Already runs standby-sync timers (`ada-standby-sync.timer` 03:15). Caveats: 4c/7G warm box, wired .75 DHCP floats (reservation pending), history of multi-day power-offs — acceptable for a *cold* standby (stale mirror is harmless). |
| **idc02** (`100.123.163.11`) | No — VPS | Degraded promote only: cloud integrations (tuya) survive; LAN cast/RTSP/esphome/LAN plugs die. Always-on, 220G free. This is the host ssot.jobs.yml literally names ("idc02 remote pull"). |
| **tony-dell** | Yes | Possible but least preferred — post-drain role is capacity/failover, not always-on duty. |
| con01 | No — VPS (EU) | Not proposed; same no-LAN problem as idc02 plus latency. |

**Pending decision:** card `tony-ha-prod-placement-26f033` may make mn01
the *prod* host — in that case this standby retargets to the loser
(omen or idc02) per that card's followups. Everything below is written
`<STANDBY>`-agnostic; substitute the chosen host.

Prereqs on the standby host (verify before Part 1):

```bash
ssh tony-omen true                        # tailnet ssh + key auth to prod
ssh tony-omen 'test -d /home/tony/.config/home-assistant'
command -v rsync podman python3 systemctl
loginctl show-user "$USER" -p Linger --value | grep -qx yes \
  || loginctl enable-linger "$USER"   # timers must survive logout
```

## Part 1 — periodic config sync (install once)

The sync is a **pull**: the standby host fetches from omen. The driver
lives on the standby, so omen being down simply means "nothing new to
pull" — no push credentials or timers needed on the flaky host.

1. **Get the script.** It rides the normal chaba checkout sync
   (`chaba-repo-sync.timer`, hourly on exec checkouts):

   ```bash
   ls ~/CascadeProjects/chaba/scripts/home-assistant/ha-standby-sync.sh
   ```

   If the host has no exec checkout, copy it once:
   `install -m755 scripts/home-assistant/ha-standby-sync.sh ~/.local/bin/ha-standby-sync`
   and use `~/.local/bin/ha-standby-sync` in the unit below.

2. **First sync** — include the recorder-DB snapshot so the standby is
   complete (history survives promotion):

   ```bash
   ~/CascadeProjects/chaba/scripts/home-assistant/ha-standby-sync.sh --db
   cat ~/.local/share/ha-standby-sync/last-sync.txt   # manifest: time, source, image ref+digest
   ```

   What lands where:
   - `~/.config/home-assistant/` — exact mirror of the prod config tree
     (`--delete` semantics): YAML, `.storage/` (auth, registries,
     dashboards, ha_mcp_tools endpoint config), `secrets.yaml`,
     `household.yml`, `www/`, `patches/`, `custom_components/`, `.git`.
   - Excluded: `home-assistant_v2.db*` (live DB), `home-assistant.log*`,
     `deps/` (reinstalled at boot, image-pinned), `tts/`, `__pycache__`,
     `.ha_run.lock`.
   - `~/.local/share/ha-standby-sync/` — state dir OUTSIDE the mirror:
     `last-sync.txt` manifest, `home-assistant_v2.snapshot.db` (--db),
     `sync.lock`.

   Guards built into the script: refuses to run on the source host, while
   a `tony-ha`/`ada-ha` unit or container is active here (split-brain),
   and on first run into a non-empty unmarked dest without `--force`.

3. **Install the timer** — `~/.config/systemd/user/ha-standby-sync.service`:

   ```ini
   [Unit]
   Description=tony-ha cold-standby config sync (pull from tony-omen)
   After=network-online.target tailscaled.service
   Wants=network-online.target

   [Service]
   Type=oneshot
   TimeoutStartSec=1800
   ExecStart=%h/CascadeProjects/chaba/scripts/home-assistant/ha-standby-sync.sh
   ```

   `~/.config/systemd/user/ha-standby-sync.timer`:

   ```ini
   [Unit]
   Description=tony-ha cold-standby config sync (hourly pull)

   [Timer]
   OnCalendar=hourly
   Persistent=true

   [Install]
   WantedBy=timers.target
   ```

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now ha-standby-sync.timer
   systemctl --user list-timers ha-standby-sync.timer
   journalctl --user -u ha-standby-sync.service -n 20   # after first tick
   ```

   Hourly matches the fleet's `chaba-repo-sync` cadence; rsync incremental
   makes it cheap. If the recorder DB should stay fresher than promote-time,
   add a weekly `--db` variant — the snapshot is consistent (SQLite online
   backup API run on the source over ssh) but can be GBs, so it is opt-in.

4. **Declare it** (host hygiene R1 — declared-or-dead):

   - `docs/ssot/infrastructure/ssot.jobs.yml` — add:

     ```yaml
     - id: ha-standby-sync
       name: tony-ha Cold-Standby Config Sync
       host: <standby-host>
       dispatch: systemd
       on_calendar: hourly
       persistent: true
       timeout: 30m
       exec: '%h/CascadeProjects/chaba/scripts/home-assistant/ha-standby-sync.sh'
       note: pull mirror of tony-ha config for cold standby (HOM-0855); runbook docs/runbooks/tony-ha-cold-standby.md
     ```

   - `docs/ssot/infrastructure/ssot.audit.hosts.yml` — under the standby
     host's `expected_services:` add
     `- {name: ha-standby-sync.timer, type: timer, scope: user}`.
   - Regenerate units: the `systemd/generated/<host>/` copies come from
     ssot.jobs.yml — keep them in sync per the jobs-file convention.

## Part 2 — promote the standby to live

Gate: only when omen is genuinely unavailable (maintenance window,
hardware work). If omen is merely tailscale-down but alive on LAN,
prefer fixing connectivity over promoting — two sources of truth is the
failure this design avoids.

```bash
# 0. Confirm prod is really gone (verify by surface, not service name)
tailscale status | grep tony-omen
ssh -o ConnectTimeout=8 tony-omen true || echo 'omen unreachable'
curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 \
  https://tony-omen.taila0626a.ts.net:8123/     # expect 000/timeout
curl -s -o /dev/null -w '%{http_code}\n' --max-time 8 \
  http://idc02.taila0626a.ts.net:8123/          # expect 502 while omen is down
```

```bash
# 1. Stop the sync timer on the standby — it must NEVER run again on this
#    host once promoted (it would pull omen's frozen config over live state)
systemctl --user disable --now ha-standby-sync.timer
rm -f ~/.config/containers/systemd/tony-ha.container   # if pre-installed; not yet

# 2. Final fresh sync (with DB snapshot for history)
~/CascadeProjects/chaba/scripts/home-assistant/ha-standby-sync.sh --db
cat ~/.local/share/ha-standby-sync/last-sync.txt
#    note the 'image:' line — ref + image id + repo digest

# 3. Restore the recorder DB snapshot (optional — skip for empty history)
cp ~/.local/share/ha-standby-sync/home-assistant_v2.snapshot.db \
   ~/.config/home-assistant/home-assistant_v2.db
```

```bash
# 4. Pin the image — do NOT use the floating :stable tag.
#    The quadlet bind-mounts frontend patch files whose filenames are
#    HA-version-specific (patches/ha-map-tiles*.js -> 52451.*); a different
#    HA build = patch mounts land on wrong/absent paths.
#
#    a) If omen is reachable enough to answer podman inspect:
ssh tony-omen 'podman image inspect homeassistant/home-assistant:stable --format "{{.Digest}} {{.Id}}"'
#    b) Otherwise use the digest recorded in last-sync.txt (captured every
#       sync). If neither exists, fall back to image transfer:
#       ssh tony-omen 'podman save homeassistant/home-assistant:stable' \
#         | podman load        # exact local image, proven migration pattern
#
#    Pull by digest on the standby:
podman pull docker.io/homeassistant/home-assistant@sha256:<DIGEST>
podman inspect --format '{{.Digest}}' \
  docker.io/homeassistant/home-assistant@sha256:<DIGEST>   # verify match
```

```bash
# 5. Install the quadlet — canonical file lives at
#    stacks/tony-dell/tony-ha/tony-ha.container (repo path keeps the dell
#    era name; it is THE tony-ha quadlet).
cp ~/CascadeProjects/chaba/stacks/tony-dell/tony-ha/tony-ha.container \
   ~/.config/containers/systemd/tony-ha.container
$EDITOR ~/.config/containers/systemd/tony-ha.container
#    REQUIRED edits:
#      Image=docker.io/homeassistant/home-assistant@sha256:<DIGEST>
#      (was :stable — pin to the digest from step 4)
#    CONDITIONAL edits:
#      delete AddDevice=/dev/video0 and /dev/video1 lines if the standby
#      has no USB cams (mn01 has none — verified 2026-10-26; the cams are
#      physically on omen/dell anyway and tony-ha already runs without
#      them since the ph5 evacuation).
#    KEEP AS-IS: Network=host, User=root, Volume=/config + all patches/*
#    mounts, Environment=TZ=Asia/Bangkok, health check.

systemctl --user daemon-reload
systemctl --user start tony-ha
systemctl --user status tony-ha --no-pager | head -20
journalctl --user -u tony-ha -n 50 --no-pager   # first boot: .storage migration, integration reload
curl -sf -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8123/   # expect 200 (may take a minute)
```

```bash
# 6. Expose on tailnet — same shape omen uses
tailscale serve --https=8123 http://127.0.0.1:8123
tailscale serve status    # confirm :8123 -> 127.0.0.1:8123
curl -s -o /dev/null -w '%{http_code}\n' \
  https://<standby>.taila0626a.ts.net:8123/       # expect 200 (TLS via tailscale serve)
```

```bash
# 7. Repoint consumers — the "flexibility layer" earns its keep here.
#    Every pointer below currently names tony-omen; flip to the standby.

# a) idc02 tailnet shadow front (stacks/idc02/tailnet-front.caddy):
#    http://:8123 block — change reverse_proxy target to
#      https://<standby>.taila0626a.ts.net:8123 { header_up Host <standby>.taila0626a.ts.net }
#    then on idc02: systemctl --user restart caddy-edge
#    (GOTCHA: `caddy reload` does NOT reach the admin API inside the
#     podman --network=host container — restart applies, ~2s blip;
#     host-migration-tony-dell.md phase-3 note)

# b) idc02 public edge — tony-ha.surf-thailand.com site block lives in
#    idc02:~/.config/caddy/Caddyfile (only some blocks are in-repo). Repoint
#    its HA upstream the same way; restart caddy-edge.

# c) stacks/web/Caddyfile — /apps/ha/tony-ha* redirect currently targets
#    https://tony-omen.taila0626a.ts.net:8123/ — update to the standby URL
#    (or better, to http://idc02.taila0626a.ts.net:8123/ so the NEXT move
#    is again a one-line upstream change).

# d) Ada voice lane on idc03 — the direct HA consumer:
#    idc03:~/.config/secrets/tony-ha/backend.env
#      HOME_ASSISTANT_URL=https://tony-omen.taila0626a.ts.net:8123/
#    -> https://<standby>.taila0626a.ts.net:8123/
#    then: ssh idc03 'systemctl --user restart ada-ha-tony.service'
#    (ada-pi-pwa env — check for the same var if that lane still exists;
#     per ssot.apps.ada_pi notes it rides ada-ha-tony now)

# e) ha_mcp_tools MCP endpoint — in-process inside tony-ha, binds the host
#    net -> :9584 on whatever host runs it. Consumers point at
#    http://tony-omen:9584/private_CtYuVkJEl28cp8qA8yXNCQ
#    (ssot.home-assistant.mcp.yml#tony_ha). Repoint MCP client configs to
#    http://<standby>:9584/... (or add an idc02 :9584 shadow block if you
#    want a stable name — optional, not currently shadowed).

# f) Live dashboards — grep for omen URLs inside HA itself:
#    on the standby: grep -rl 'tony-omen.taila0626a.ts.net' \
#      ~/.config/home-assistant/.storage/lovelace* \
#      ~/CascadeProjects/chaba/docs/home-assistant/dashboards/
#    tony-ha.surf-thailand.com embeds are host-independent — they keep
#    working once (b) is repointed. Fix any omen-absolute iframes/weblinks
#    via the usual lovelace websocket path (ssot.home-assistant.howto.yml).

# g) host-coupled helpers inside the config dir (from the placement
#    research — verify each, most are dormant):
#      - go2rtc refs 127.0.0.1:1984/8554/8555 -> if go2rtc stays on omen,
#        repoint to omen's LAN IP in configuration.yaml (same L2 segment
#        from mn01; from idc02 these die regardless — degraded mode)
#      - ha-live bridge :9005 -> tailnet :8444 serve mapping is an omen
#        tailscale-serve entry; re-create on the standby only if the voice
#        push-to-talk lane is needed during the outage
#      - command_line usb_test_hub (disabled), update-cam-frame.sh,
#        node-red (:1880 stays on omen — repoint its HA-side callers if any)
```

```bash
# 8. Verify by surface — producer AND consumer proof
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8123/                    # 200 local
curl -s -o /dev/null -w '%{http_code}\n' https://<standby>.taila0626a.ts.net:8123/ # 200 tailnet
curl -s -o /dev/null -w '%{http_code}\n' http://idc02.taila0626a.ts.net:8123/      # 200 via shadow
curl -s -o /dev/null -w '%{http_code}\n' https://tony-ha.surf-thailand.com/       # 200/302 via CF Access
#    toggle a real device (plug/cast), confirm an automation fires,
#    confirm Ada voice lane answers (it consumes HOME_ASSISTANT_URL)
```

## Rollback / fail-back

The standby is only "live" after step 7's repoints; omen's own state is
untouched (its ha-config-backup keeps snapshot-committing whenever it is
up — do NOT let omen's tony-ha start while the standby serves).

```bash
# fail back to omen:
systemctl --user stop tony-ha                       # on standby — FIRST
#    tailscale serve --https=8123 off               # on standby
#    repoint fronts/consumers in step 7 back to tony-omen
ssh tony-omen 'systemctl --user start tony-ha'      # omen resumes from ITS
                                                    # own config (fresher
                                                    # than the mirror if it
                                                    # was up during standby)
```

Split-brain rule (non-negotiable): **never run two live tony-ha
containers.** The recorder DB, .storage registries, and cloud integration
sessions all diverge. The script's guard enforces this on the sync side;
the promote side enforces it by stopping the standby before omen starts.

## Post-promotion bookkeeping (do in the same session)

1. `docs/ssot/infrastructure/ssot.home-assistant.instances.yml` — flip
   `tony-ha.host` to the standby host; update `url.tailscale`,
   `status.notes`.
2. `docs/ssot/infrastructure/ssot.system-map.yml` — `homes[tony-ha].host`
   and `services.tony-ha` entries.
3. `docs/ssot/infrastructure/ssot.routes.yml` — tony-ha service line.
4. `docs/ssot/infrastructure/ssot.home-assistant.tony.yml` — this file is
   already stale (still says `host: tony_dell`, `ha_mcp` :9584 notes) —
   update host/runtime fields while you are in there.
5. `docs/ssot/infrastructure/ssot.audit.hosts.yml` — move
   `tony-ha.service`/timer expectations omen→standby; remove
   `ha-standby-sync.timer` (retired on promotion) or re-point it if the
   standby stays cold for a NEW prod.
6. Decide the standby's next role: re-arm the sync timer against the NEW
   prod host (`--source`/env or a second job entry), or leave the host
   clean. Record the choice on the card.
7. Consumer-reference audit (migration runbook exit gate): grep deployed
   artifacts for `tony-omen.taila0626a.ts.net:8123` and `tony-omen:9584`
   — dashboards JSON, `stacks/**/*.js` card sources, flows, env files.

## What this does NOT cover

- **ada-ha** — same host, same failure domain. If the outage is "omen
  down", ada-ha dies too. The identical pattern applies
  (`~/.config/ada-ha`, `stacks/tony-dell/ada-ha/ada-ha.container`,
  shadow `:8125`); extend the sync script's `--source/--dest` or add a
  second job if wanted. Deliberately out of scope here — lab tier.
- **michael-ha** — Nabu Casa cloud, unrelated failure domain.
- **kk-ha** — lives on idc03, unrelated.
- **go2rtc / node-red / camera-panel / cast timers** — separate omen
  services HA depends on; they stay on omen. On an mn01 promote they
  remain reachable over LAN/tailnet with the repoints in step 7g; on an
  idc02 promote the LAN-bound ones are simply dead (degraded mode).
- **The omen→standby direction** — this is standby-pulls-prod. If omen
  is the host being *evacuated* (planned move, not outage), the
  dell→omen rsync procedure in host-migration-tony-dell.md phase 5 is
  the closer precedent.

## Verification status

- `status: partial` — every referenced path/host/unit verified against
  repo SSOT + stacks + the 2026-10-19/20 evacuation record; the sync
  script dry-runs clean. First live install + one promote drill is the
  remaining verification (recommend a scheduled drill once mn01 is armed).
