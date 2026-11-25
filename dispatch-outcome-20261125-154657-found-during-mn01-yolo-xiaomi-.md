# Dispatch outcome — mn-ha-dev-crash-looped-40x-on-mn01-2026-986f32

## Root cause (solved)

`mn-ha-dev.service` on mn01 was NOT crashing — it was being **killed by
`earlyoom.service`** (userspace OOM killer). mn01 has 7.3GB RAM and
**zero swap**, so earlyoom's default condition (MemAvailable ≤10% AND
swap ≤10%) is permanently armed. Every time MemAvailable dipped under
~600MiB — which happens whenever devin dispatch tasks, the 3 yolo
server.py instances, gnome/Xorg, ada-voice standby, netdata, or the
XMEye VMS stack spiked — earlyoom SIGTERMed `python3 -m homeassistant`
(the highest oom_score victim at ~450-840MB RSS, oom_score_adj=200).

HA handles SIGTERM gracefully → exit 0 → s6 "finish process exit code
0" → container exits → `Restart=always` (RestartSec=10) brings it back.
That is why every exit looked clean. The intermittent "received signal
15" / `closed_incorrect=1` recorder runs (and the repeated sqlite
"not shutdown cleanly" warnings) are the same kills landing mid-shutdown.

## Evidence

- `journalctl -u earlyoom` on mn01: `sending SIGTERM to process ...
  "python3 -P -m homeassistant --config /config"` at **every** HA exit
  timestamp — 44 of 51 earlyoom kills since 2026-11-24 were HA python.
- `home-assistant_v2.db` `recorder_runs`: 45 runs 10:44→now; the
  `closed_incorrect=1` runs map 1:1 to the signal-15 exits.
- `events` table: **zero** `call_service` events for domain
  `homeassistant` all-time — the restart/stop service path was never
  used; no HA-side automation/script calls it (automations.yaml `[]`,
  scripts.yaml empty, ha_mcp_tools never calls `hass.async_stop`).
- No kernel oom-kill, no systemd-oomd kills, no MemoryMax on the unit.
- earlyoom also killed: VMS.exe ×5 (~700-970MB each), vms-snap.py,
  a yolo `server.py`, a chrome OAuth proc — host-wide pressure, not an
  HA defect.
- **Correction to the parent card's guess**: yolo-xiaomi.service's
  02:38 "deliberate stop" was almost certainly earlyoom too —
  earlyoom SIGTERMed its `server.py` at 02:38:22; python exited 0,
  `Restart=on-failure` doesn't revive clean exits. Same signature.

## Answers to the card's TODO

- **Issuer**: earlyoom SIGTERM — identified above.
- **MemoryMax/RestartSec tuning**: NO. MemoryMax would SIGKILL python
  mid-checkpoint and manufacture the sqlite corruption already seen.
  Restart=always/RestartSec=10 work correctly — leave them.
- **Smaller footprint**: HA ~700-840MB peak is normal; the lever is
  host headroom, not HA config.
- **Stability**: NOT stable — NRestarts=43 at 09:32 UTC, kills recur on
  every MemAvailable<10% excursion. "Stable since 05:43" was a quiet
  window. Still restarting as of this writing (latest kill 09:32:15).

## Recommendation (needs Tony's call — board request raised)

1. ★ **Add zram swap on mn01** — mirror tony-dell's
   `/etc/systemd/system/zram-swap.service`, sized ~4G zstd (dell uses
   8G on 16GB; mn01 has 7.3GB). Proven in-house pattern
   (docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-podman-lock-wedge.yml);
   140GB free on / if a disk swapfile is preferred instead.
2. earlyoom `-m 5` — reduces kill frequency, doesn't fix pressure.
3. Reduce mn01 load — dispatch lane cap 2→1, consolidate yolo ×3.
4. Do NOT: MemoryMax on the quadlet, or earlyoom `--avoid homeassistant`
   (just relocates kills onto devin tasks).

## Deliverables

- `docs/ssot/jobs/infrastructure/2026-11-25-mn01-mn-ha-dev-earlyoom-kills.yml`
  — full timeline, evidence, verdicts, verification commands.
- This outcome doc.
- Card comms + board request posted to
  `mn-ha-dev-crash-looped-40x-on-mn01-2026-986f32`.

## How to verify

```
ssh mn01 'journalctl -u earlyoom.service --since "2026-11-25" | grep "sending SIGTERM"'
ssh mn01 'systemctl --user show mn-ha-dev.service -p NRestarts,ActiveEnterTimestamp'
ssh mn01 'free -m; swapon -s'
```

lessons:
- "Clean exit code 0" from a podman HA container is NOT proof of an
  HA-side stop — earlyoom SIGTERM produces graceful exit 0; always check
  `journalctl -u earlyoom` before theorizing about HA internals.
- mn01 has no swap: any memory spike there gets arbitrated by earlyoom,
  which kills whatever has the highest oom_score — serially taking out
  HA, VMS.exe, yolo, and chrome. Treat mn01 service restarts as
  earlyoom suspects first.
- `recorder_runs.closed_incorrect=1` in home-assistant_v2.db cleanly
  separates SIGKILL/signal-path deaths from graceful SIGTERM exits.
- A `Restart=on-failure` unit "dying cleanly" via SIGTERM looks exactly
  like a deliberate `systemctl stop` in the journal — check earlyoom
  before assuming manual triage (the yolo-xiaomi "deliberate stop" was
  earlyoom).
