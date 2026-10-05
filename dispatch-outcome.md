# dispatch outcome — gev-bridge (2026-10-05)

## What changed

- `stacks/tony-dell/gev-gemini/tools-check.mjs` (new) — drift guard. Re-extracts
  `GEV_REALTIME_TOOLS` from `~/gods-eye-view/vite.config.js` (balanced-bracket
  literal scan, evaluated via `new Function`), strips `additionalProperties`/
  `additional_properties` recursively (mirrors `bridge.py _clean_schema`), and
  deep-diffs against committed `tools.json` with per-path output. Exit 1 on
  drift; `--write` regenerates; `--config`/`--tools`/`$GEV_VITE_CONFIG` overrides.
- `stacks/tony-dell/gev-gemini/live-check.py` (new) — live ws smoke: connect →
  `status` → `{"type":"text"}` → `function_call` → `tool_response` → `done`.
- `stacks/tony-dell/gev-gemini/README.md` (new) — runbook for both checks.
- `docs/ssot/jobs/gev/2026-10-05-tools-json-regen-guard.yml` — job record.
- `tools.json` left **unchanged** (see drift note).

## Findings

- **Guard works — and immediately caught real bidirectional drift.** Committed
  `tools.json` is AHEAD of the source repo: the 2026-10-04 `move_camera`
  zoom/fly/`amount` + extended direction enums exist only in the deployed
  bundle/tools.json (source_port still pending). Source has its own newer
  bits (`stop` motion, reworded descriptions). Do NOT `--write` until the
  source port lands — it would regress the live declarations.
- **Live ws path was broken since the Sep-30 unpinned rebuild.** Voice
  sessions died with `timed out during opening handshake`; the Oct-3
  traceback shows the timeout expiring while `loop.getaddrinfo` was still
  queued, plus a 3m23s gap between adjacent synchronous log lines — the
  bridge's event loop was freezing under host memory pressure (psi avg300
  1.68, swap 11.3G/16G). Fresh connects with the same SDK/config succeeded
  in 0.6s, so neither the model name, the key, nor the schema was at fault.
  `systemctl --user restart gev-gemini` cleared it; watch for recurrence
  while the host stays memory-pressured.

## Verification results

- `node tools-check.mjs` → FAIL with precise per-path diff (expected — real drift)
- `--write` to temp → check PASS (round-trip proven; 28 decls, 0 `additionalProperties`)
- `python3 live-check.py` → PASS on `ws://127.0.0.1:8789`:
  text → `function_call zoom_to_globe` → `tool_response` → spoken reply + `done`
- `python3 live-check.py --url wss://tony-dell.taila0626a.ts.net/apps/gev-live/ws`
  → PASS (full cycle through Caddy)
- `node scripts/ssot-validate-all.mjs` → 1176/1176 valid, 0 errors

## Follow-ups for the operator

- Port the bundle-side `move_camera`/`adjust_camera_zoom` declarations into
  `~/gods-eye-view/vite.config.js` (per `jobs/gev/2026-10-04-gev-map-zoom-flight.yml`
  source_port), then `node tools-check.mjs --write`.
- Consider pinning `requirements.txt` (genai 2.25.0 + websockets 16.1.1 are the
  verified-good set) so the next rebuild doesn't silently move the target.
