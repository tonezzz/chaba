# dispatch outcome — ops-kkmac-agent-update-temps (kk-mac telemetry agent)

## Result: DONE (verified, no changes needed)

kk-mac is **back online** — tailscale shows it active (direct 192.168.0.101),
ssh daemon answers. This host (tony-macbook) has no authorized key for kk-mac;
access works via `ssh tony-dell 'ssh kk-mac ...'` which lands as `kkkakk`.

Card goal state, verified live:

- Installed `~/.local/share/device-telemetry/agent.py` on kk-mac has
  md5 `8247c31e15aea7b218f6166a3fefa4be` — **identical to current
  `origin/master:scripts/device-telemetry/agent.py`**. The card's pinned
  md5 `132c7c8c…` was the a4504a72 version; two newer commits
  (`a3ed8fd` macOS temp retry/cache, `63b2fa9` TEMP_CACHE_S doc) landed
  after the card was written, and kk-mac already carries them
  (file mtime 2026-11-25 18:56; backups `agent.py.bak-20261125` and
  `agent.py.bak-retry` show earlier same-day update attempts).
- launchd `com.telemetry.agent` is loaded, `StartInterval=300`,
  `DEVICE_TELEMETRY_NAME=kk-mac`, `DEVICE_TELEMETRY_MDBB=http://100.102.134.91:11026/v1`.
- Ran the agent once manually per spec → `{"hist": true, "latest": true,
  "key": "kk-mac/1795608787"}`.
- Fetched `device-telemetry/kk-mac/latest` from MDDB: `temp_c: 40.0`,
  `temp_zones: {"cpu": 40.0}`, `thermal_pressure: "Nominal"`,
  `temp_source: "live"`, `services.device-telemetry.state: running`.
  **Named zones confirmed** — the card's done-condition is met.

## Side observations (reported on card, not acted on)

- Stale MDDB doc `device-telemetry|192/latest` (device name "192",
  ts≈1794880208 ~Nov 19) still exists — pre-`DEVICE_TELEMETRY_NAME`
  artifact from kk-mac's own beacon; harmless, could be deleted.
- kk-mac telemetry shows `disk_pct: 93.5`, `swap_pct: 91.9` — worth a
  separate look.

## How to verify

```
ssh tony-dell 'ssh kk-mac "md5 -q ~/.local/share/device-telemetry/agent.py"'
# expect 8247c31e15aea7b218f6166a3fefa4be
curl -s http://100.102.134.91:11026/v1/get -H 'Content-Type: application/json' \
  -d '{"collection":"device-telemetry","key":"kk-mac/latest","lang":"en"}'
# expect temp_zones {"cpu": ...} and fresh ts
```

## lessons:

- kk-mac ssh only works from tony-dell (`ssh tony-dell 'ssh kk-mac …'`,
  lands as kkkakk); tony-macbook has no authorized key despite the
  `kk-mac` hostname resolving on the tailnet.
- Card-pinned file md5s go stale when the source file keeps moving —
  always diff installed-vs-`origin/master`, not installed-vs-pin.
- MDDB `/v1/search` is fuzzy/laggy for exact-key lookups; use
  `POST /v1/get {"collection","key","lang"}` for point reads.
