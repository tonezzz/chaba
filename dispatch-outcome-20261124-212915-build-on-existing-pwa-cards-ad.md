# Dispatch outcome — ada-opencode-repair-menu-card (ADA-1130)

Commit: `e177d70249` on `dispatch/20261124-212915-build-on-existing-pwa-cards-ad` (worktree only; not pushed, not deployed).

## What changed

- `stacks/tony-dell/{ada-ha,tony-ha}/www/ada-chat-card.js` (+221 lines each, byte-identical): new QC panel pinned between the status row and transcript. Config keys `picker_url` (default `http://tony-dell.taila0626a.ts.net:8777`, `""` disables) and `qc_poll_s` (default 60, min 5). Panel polls `GET /api/session`; when `comparison.last_landed.asset_id` lacks a `<asset>_qc_decision` key it shows the candidate thumbnail (`/img/<asset>`), asset+lane subtitle, an optional note field, and four actions: Keep / Reject / Revise (POST `/api/qc-decision {asset, decision, note}`) and Repair region (opens `<picker_url>/?img=/img/<asset>` — records no decision; the mask-picker submit flow already auto-lands a repair render via inbox-processor → land-render gemini-image).
- `scripts/adobe-stock/picker-server.py` (+~20): CORS for cross-origin card fetches (`Access-Control-Allow-Origin: *`, OPTIONS preflight → 204, no-store on API JSON); `/api/qc-decision` now also posts a board comment audit line.
- `scripts/adobe-stock/mask-picker.html`: bare `?img=<asset>` resolves through `/img/<asset>`.
- `scripts/adobe-stock/inbox-processor.py`: accept `.jpeg` candidate extension.
- `tests/ha/ada-chat-card/`: `server.py` gained a stateful `/qc-picker/*` fixture (`/api/session`, `/api/qc-decision` → `QC_STATE`, `/img/<asset>`, `/__control`, `/__state`); `harness.html` gained per-scenario `SCENARIO_CFG` mount config (`picker_url:""` default off) + a `qc-panel` scenario; `preview-bridge.mjs` lists the scenario; `README.md` documents it.
- `docs/ssot/jobs/ada/2026-11-24-ada-chat-card-qc-panel.yml`: job trail (design, verification, remaining deploy steps).

## Result

All card actions implemented; nothing pushed or deployed per dispatch rules. The ada-ha surface is verified through the dedicated browser harness (the card's designated verification path — precedent: verified-in-worktree, no HA deploy needed), not by live ada-ha.

## Verify

```
~/.local/node24/bin/node tests/ha/ada-chat-card/preview-bridge.mjs --spawn-server --scenario all
# -> verdict: PASS, 15/15 scenarios incl. qc-panel + mobile-viewport,
#    evidence in tests/ha/ada-chat-card/evidence/
```

`qc-panel` scenario asserts: panel hidden until `/__control` sets a pending asset; thumb decodes; all 4 buttons present; keep/reject+note/revise POST correct payloads to `/qc-picker/api/qc-decision`; repair opens `?img=` and records no decision. The pending-asset detection was also validated against the real Drive SESSION.json shape (`comparison.last_landed`, `<asset>_qc_decision` keys).

Live enablement (not done here — deploy is out of scope): sync the two `www/ada-chat-card.js` copies to ada-ha, restart picker-server for the CORS/no-store changes, and set `picker_url` config — picker serves **http** on tony-dell:8777, so https HA viewers need `picker_url:""` (panel off) or a TLS route; this is documented in the job doc and card header comment.

lessons:
- `preview-bridge.mjs` without `--spawn-server` requires a fixture server already on its port — always pass `--spawn-server` for standalone verification runs.
- `--scenario all` still runs `mobile-viewport` implicitly; scenario count in evidence/results.json reflects the last run only — re-run the full suite before committing evidence.
- picker-server is plain http on tony-dell — HA dashboards served over https hit mixed-content; the card therefore defaults `picker_url` config-driven and documents the TLS/`""` escape.
- The two ada-chat-card.js copies (ada-ha + tony-ha) must stay byte-identical — diff them after every edit.
