# ada-chat-card browser harness

Browser-level verification for `stacks/tony-dell/ada-ha/www/ada-chat-card.js`
— the HA Lovelace card behind card `openchamber-ada-card-preview-harness`
(ADA-1037). No HA deployment needed: the card runs against a fake
WebSocket + stub `hass` inside a plain page.

## Pieces

| File | Role |
|---|---|
| `harness.html` | Test page. Loads the real card JS, stubs `WebSocket`/`hass`/`window.open`, exposes `window.__acc*` hooks, runs named fixture scenarios. |
| `server.py` | Fixture server (worktree root as docroot). Adds `/dl/` (attachment), `/gone/` (410), `/bogus/image.png` (200 HTML), `/apps/yolo/api/image` (path-pattern image), `/api/auth/status` stub. |
| `fixtures/` | Real media: png/gif/mp4/webm (ffmpeg-generated), link-target page, download note. |
| `preview-bridge.mjs` | Drives the suite through **OpenChamber Preview**: registers as a browser-capable client on `/api/openchamber/events?browser=1`, serves `browser-control-request`s over the real `/api/openchamber/control` → claim → result plane, executes them in headless Chrome (Playwright `channel:"chrome"`), writes `evidence/`. `--direct` bypasses OpenChamber for debugging. |
| `evidence/` | Durable results: `results.json` (per-scenario checks + console problems), `.openchamber/screenshots/` (captures written by OpenChamber's own `writeScreenshot`), `shots/` (bridge copies). |

## Run

```bash
# full suite through OpenChamber Preview (needs openchamber.service on :3000
# and its uiPassword in ~/.config/openchamber/run/openchamber-3000.json)
~/.local/node24/bin/node tests/ha/ada-chat-card/preview-bridge.mjs --spawn-server

# one scenario, or a debug run without OpenChamber
~/.local/node24/bin/node tests/ha/ada-chat-card/preview-bridge.mjs --spawn-server --scenario push-video
~/.local/node24/bin/node tests/ha/ada-chat-card/preview-bridge.mjs --direct --spawn-server --scenario all
```

Manual: `python3 tests/ha/ada-chat-card/server.py --port 8777` then open
`http://127.0.0.1:8777/tests/ha/ada-chat-card/harness.html?scenario=all`.

## Scenarios (acceptance mapping)

- `connect` — FakeWS handshake: ws URL binds `channel=web&chat_id=web-<member>`, `ready` → Connected.
- `text-urls` — `_fillBubble`: image-ext + `/image?v=` path URLs → `<img>`, page/download URLs → `<a target="_blank" rel="noopener">`.
- `push-image` / `push-video` / `push-mixed` — `chat_push` `image_url`/`video_url` → `img.acc-media` / `video.acc-media[controls]`; decode verified (`naturalWidth`/`videoWidth`).
- `push-empty` — empty pushes drop quietly (whitespace-only text still renders — observed behavior).
- `push-broken` — 410/404/200-HTML media: elements render, decode fails (`naturalWidth=0`). Expected console resource errors, classified.
- `push-nonhttp` — `file:`/`javascript:`/`data:`/`//`/`ftp:` media URLs rejected by the `^https?://` guard.
- `stream-rerender` — transcript deltas stay raw text mid-stream; `response_completed`/`response_interrupted` re-render URLs into media/links.
- `click-open` — img click → `window.open(url)`; anchor contract `target=_blank rel=noopener`.
- `download-link` — attachment URL renders as anchor; server sends `Content-Disposition: attachment`.
- `qc-panel` — Adobe Stock QC panel (card ada-opencode-repair-menu-card): `picker_url` → stateful `/qc-picker/*` fixture; hidden→shown on pending candidate, thumb decode, 4 buttons, keep/reject(+note)/revise POST `/api/qc-decision`, repair opens `?img=/img/<asset>` with no decision recorded. Other scenarios mount with `picker_url:""` (panel off).
- `mobile-layout` — 360px stage + `browser.resize mobile` (390×844): no horizontal overflow, media capped at 100%.

## Notes

- "OpenChamber Preview" here means the real browser-control plane
  (`/api/openchamber/control` + SSE claim/result). The bridge is the
  browser-capable client the broker was missing (no desktop app is
  connected on idc02); it executes actions in headless Chrome — same
  engine as the desktop BrowserPane. When Tony's desktop client is
  connected it claims requests first via `preferredConnectionId`.
- Expected console noise exists only in `push-broken` (410/404/invalid
  image payloads) — `unexpectedProblems` filters those; everything else
  must be clean (`pageerror`/`rejection` are never excused).
