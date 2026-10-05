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
