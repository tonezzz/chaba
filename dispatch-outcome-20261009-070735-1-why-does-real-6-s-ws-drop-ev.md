# dispatch outcome — vcast-bridge-registry-bugs

## 1. WHY real-6's ws drops every 1-3min — findings

**Not the Caddy/tailscale hop.** A probe ws held through the identical path
(`wss://tony-dell.taila0626a.ts.net/api/input-bridge/ws`, joined `vcast-ctl`)
stayed up >10 minutes with the relay's 30s JSON pings arriving on time — a
proxy idle-timeout < that window would have killed it. Caddy `reverse_proxy`
has no ws timeout anyway.

**Not the nav path.** `nav` casts only retarget a pane `<iframe>` — the parent
page (and its ws) never navigates; only a `reload` cast does
`location.replace()`. The staged GEV bundle never touches
`top`/`parent.location`.

**Client-side, correlated with the GEV cast.** Live `/displays`: real-6's
current binding (screen-8, idle) has been connected >1h without a drop, while
every dead entry's last state is `nav | 0:/apps/gev/`. Leading suspect:
headless-Chromium renderer death (Cesium/WebGL under `--use-angle=swiftshader`,
no GPU) or browser OOM on idc02. A renderer crash also explains wedging:
Playwright's `page.waitForEvent("close")` never fires for a crashed tab.

**Instrumentation now in the diff** (will answer definitively post-deploy):
server logs every ws close with `code=`, `reason=`, screen, remote, age
(1001=client nav/reload, 1006=abnormal/proxy/crash, 1000 clean); protocol-level
ping/pong + terminate kills half-open sockets in ~60s; the page logs close
codes via `console.error` (vcast-real pipes to journald); vcast-real logs
`page.on("crash")`, `browser.on("disconnected")`, and force-relaunches a
wedged renderer via a 30s `page.evaluate` liveness probe.

## 2–4. Registry fixes (stacks/web/input-bridge/server.mjs)

- **Grace reclaim** — on live-binding close the entry is stamped
  `disconnected_at` and held `VCAST_GRACE_MS` (default 60s) for in-place
  rebind; past grace the sweep deletes it (replaces the 72h prune). Dead
  entries stop pinning names; `/displays` shows `disconnected_at`.
- **Claim honoring** — `/claim` accepts `{name:screen-N}`, `{want_screen:N}`,
  or `{screen:N}`. Wanted is honored when free, rebound when held by a dead
  same-name entry, or evict-reclaimed when held by a dead different-name
  entry; only a LIVE different-name holder deflects to lowest-free. The old
  unconditional `used` check was the drift bug (real-6 owned slots 1,6,8,9).
  `register-display` also honors `want_screen` when the slot is free.
- **Release tombstones** — `/release` persists `registry.tombstones[name]`
  in displays.json, sends `unpaired` + closes the socket, and flushes
  `lastCast` for the room. `registerDisplay` refuses a tombstoned name (even
  when the old key still resolves — revoke lag/failure was the resurrection
  path) until a fresh `/claim` lifts it. State writes remain update-only.
- **vcast-real.mjs** — `VCAST_KEY_FILE` persists the minted api_key (seeded
  into the fresh browser's localStorage via `addInitScript`, along with
  `VCAST_DEV_ID` device_id) so a relaunch self-registers instead of
  re-minting through /claim; `claim()` short-circuits when the label is
  already connected (prevents the 120s-timeout relaunch loop on the
  persisted-key path); crash/disconnect/watchdog logging above.
- **vcast page** — `ws.onclose` logs code/reason/clean/screen/state;
  `sw.js` bumped to `vcast-v4` per the deploy-bump rule.

## Result / verification

- New `vcast-registry-check.mjs` (loopback server + stub ada): **14/14 PASS**
  — claim honor-when-free, grace retention+rebind, grace-expiry sweep, dead
  holder rebind (no drift), live-holder deflection, want_screen, release
  delete + unpaired, tombstoned re-register refused, no resurrection, fresh
  claim lifts tombstone.
- Regression: flap 7/7, cast 17/17, handoff 6/6 — all green via
  `podman run --rm --network=host -v $PWD:/app -w /app
  mcr.microsoft.com/playwright:v1.47.2-jammy node <check>` (runner has no
  host node; `npm install` ran in-container — node_modules is gitignored).
- Runner: `node --check` clean on all touched JS.

## Not deployed (dispatch mode)

Deploy steps when approved: rsync `stacks/web/input-bridge/server.mjs` to
idc03 `~/apps/input-bridge/` + `systemctl --user restart input-bridge`;
rsync `stacks/web/public/apps/vcast/` to the tony-dell web mount; update
idc02 `vcast-real@N` units with `VCAST_KEY_FILE=%h/.local/share/vcast-real/screen-%i.key`
and `VCAST_DEV_ID=vcast-real-%i`. Post-deploy: the existing dead entries
(1,6,9 = vcast-real-6; 3 = Browser) are swept automatically ~60-90s after the
relay restart; watch `journalctl --user -u input-bridge` `[vcast] ws closed
code=` lines for the real-6 answer.

Trail: `docs/ssot/jobs/vcast/2026-10-09-vcast-registry-bugs.yml`;
SSOT updated (`ssot.apps.vcast.yml` registry-lifecycle + testing sections);
card note updated.
