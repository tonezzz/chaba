# Dispatch outcome — gev-relay-frame-loading-404

Card: `gev-relay-frame-loading-404` — "gev_command 404s when GEV client
still in frame-loading — should be retryable".

## Finding

Two distinct defects shared the symptom:

1. The literal HTTP 404 in the 2026-10-08 incident was the missing
   `uri strip_prefix /apps/gev-cmd` on the edge route — bridge.py only
   knows `/command`, so `/apps/gev-cmd/command` 404'd. This was already
   fixed live Oct-9 19:55 and made durable in `ssot.routes.yml`
   (`strip:`), but the checked-in `stacks/web/Caddyfile` was still in
   the pre-fix state. Synced to `handle_path` (what render-routes.py
   emits for this route — verified by running it).
2. The underlying race the card describes is real independent of the
   strip bug: between vcast nav completing and the GEV page's
   `?remote=1` websocket + `hello {screen,pane}` landing, a
   screen-targeted `POST /command` found zero remotes and returned a
   bare `200 {ok:false:"no GEV remote on screen N"}` — un-actionable
   for a model caller.

## Change (bridge.py, stacks/tony-dell/gev-gemini/)

- `_dispatch` gains `grace_s`: while zero targets match, it re-polls
  `REMOTE`/`CLIENTS` every 0.25s until the deadline. This covers both
  the ws-not-yet-connected and connected-but-hello-pending windows.
- `do_POST /command` passes `grace_s=GEV_REMOTE_GRACE_S` (default 12s,
  matching the tool's "~10s" hint) only for screen-targeted calls;
  broadcasts (`screen=None`) keep `grace=0` — no behavior change.
- If the grace elapses the response keeps the `200 + ok:false` channel
  (the ada-pi tool relays the `error` text; HTTP-error paths lose the
  body) and adds `retryable:true`, `retry_after_s` (default 5,
  `GEV_REMOTE_RETRY_S`) and "client may still be loading; retry in ~Ns".
- `.result()` timeout extended to `wait_s + grace_s + 5`; `screen`
  coerced to int like `pane` so a JSON string can't silently miss.

Net effect: the common "cast nav → immediate flyTo" case now just works
(command waits ~a few seconds for the remote, then delivers), and the
residual failure is explicitly retryable with a hint.

## Files

- `stacks/tony-dell/gev-gemini/bridge.py` — grace loop + retryable
  contract + screen coercion
- `stacks/tony-dell/gev-gemini/bridge-check.py` — NEW deps-free
  self-test (websockets/genai stubbed via sys.modules)
- `stacks/tony-dell/gev-gemini/README.md` — grace envs + retry contract
- `stacks/web/Caddyfile` — `handle` → `handle_path` for gev-cmd
  (drift sync vs live fix + ssot)
- `docs/ssot/apps/ssot.apps.gev.yml` — remote-clients contract updated
- `docs/ssot/jobs/gev/2026-10-10-gev-relay-frame-loading-grace.yml` —
  job record
- `docs/ssot/kanban/cards/gev-relay-frame-loading-404.yml` — done comm

## Verify

- `python3 stacks/tony-dell/gev-gemini/bridge-check.py` → 13 checks
  pass (grace timing, retryable shape, late-remote delivery,
  wrong-screen miss, broadcast fast path, pane mismatch, health)
- YAML: all touched files `yaml.safe_load` clean (node unavailable in
  env for ssot-validate-all.mjs)
- Live: needs `podman build -t localhost/gev-gemini:latest
  stacks/tony-dell/gev-gemini` + `systemctl --user restart
  gev-gemini.service` on tony-dell — NOT done (deploy approval-gated).
  After deploy: `POST /apps/gev-cmd/command {name, screen:N}` right
  after a fresh cast should deliver instead of failing.

## Follow-ups

- ada-pi `gev_command` "wait ~10s after casting" usage hint can be
  relaxed once the bridge is live (separate repo — noted on the card).
- Commit `9d5a04b2` on branch
  `dispatch/20261010-091732-gev-command-404s-when-gev-clie` — not pushed.
