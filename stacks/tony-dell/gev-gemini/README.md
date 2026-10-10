# gev-gemini — Gemini Live bridge for God's Eye View

Quadlet `gev-gemini.service` (`localhost/gev-gemini`, host network). Proxies
browser clients to a Gemini Live session: voice clients on `ws://0.0.0.0:8789`
(Caddy `/apps/gev-live/ws`), passive remote-control clients on the same port
with `?remote=1`, and a loopback HTTP command endpoint on `127.0.0.1:8790`
(`/command`, `/command/health`) that injects `function_call` frames.

`tools.json` is a snapshot of `GEV_REALTIME_TOOLS` in the gods-eye-view source
(`~/gods-eye-view/vite.config.js`), with `additionalProperties` stripped —
Gemini Live rejects that key. `bridge.py` also strips it at load as a
belt-and-suspenders.

## Drift guard — run before/after any GEV_REALTIME_TOOLS change

```bash
cd stacks/tony-dell/gev-gemini
node tools-check.mjs            # exit 1 with a per-path diff when tools.json drifts
node tools-check.mjs --write    # regenerate tools.json from the source
node tools-check.mjs --config /path/to/vite.config.js   # or $GEV_VITE_CONFIG
```

Only `--write` when the gods-eye-view source is the intended truth — see the
source_port caveat in `docs/ssot/jobs/gev/2026-10-05-tools-json-regen-guard.yml`
(the 2026-10-04 bundle-side move_camera zoom/fly changes are still ahead of
the source repo).

## Guards (bridge-side, deterministic)

Model proposes, bridge enforces — same posture as Ada's provider:

- **Tool budget**: `GEV_TURN_TOOL_BUDGET` (default 12) calls per turn; excess
  are dropped and the model gets an error response.
- **Confirm gate**: `GEV_CONFIRM_TOOLS` (default `clear_annotations,control_cctv`)
  plus `annotate_map` with `persist=true` require the user's last utterance
  (input audio transcription, or the typed-turn text) to affirm — same
  regex + negation/question vetoes as ada-pi's `_user_confirmed`. Blocked
  calls get a synthetic `tool_response` telling the model to ask first.
- **Ops events**: guard interventions POST to MDDB (`GEV_MDDB_URL`,
  `GEV_OPS_COLLECTION`=`gev-ops-events`) so they show in the digest.

`/command` (loopback HTTP) is intentionally ungated — callers like Ada's
`gev_command` are already gated upstream.

Screen-targeted `/command` calls wait `GEV_REMOTE_GRACE_S` (default 12s)
for a matching remote to register — a freshly casted page is still in
frame-loading when the first `gev_command` lands (the 2026-10-08
nav-then-404 gap). If the grace elapses the response is
`{ok:false, retryable:true, retry_after_s:N}` with "client may still be
loading; retry in ~Ns". `python3 bridge-check.py` self-tests the grace +
retry contract without websockets/genai deps.

## Live path smoke

```bash
python3 live-check.py                                    # ws://127.0.0.1:8789
python3 live-check.py --url wss://tony-dell.taila0626a.ts.net/apps/gev-live/ws
```

Opens a real Gemini Live session (API quota applies), sends a text turn that
must produce `zoom_to_globe`, answers it with a `tool_response`, and waits for
`done`. First check doubles as a tools.json schema validation — the session
setup is rejected if a bad declaration slips through.

Rebuild after changing `bridge.py`/`tools.json`/`Containerfile`:

```bash
podman build -t localhost/gev-gemini:latest stacks/tony-dell/gev-gemini
systemctl --user restart gev-gemini.service
```

NOTE: `requirements.txt` is unpinned — a rebuild pulls the newest
`google-genai`/`websockets`. The 2026-09-30 rebuild landed genai 2.25.0 +
websockets 16.1.1; pin versions if a future rebuild regresses.
