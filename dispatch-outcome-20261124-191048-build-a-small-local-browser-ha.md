# Dispatch outcome — openchamber-ada-card-preview-harness

## What changed

Built a self-contained local browser harness for
`stacks/tony-dell/ada-ha/www/ada-chat-card.js` under
`tests/ha/ada-chat-card/` (37 harness files + job doc; commit
`38965e66da` on `dispatch/20261124-191048-build-a-small-local-browser-ha`,
not pushed, not deployed):

- `server.py` — fixture HTTP server on `127.0.0.1:8777`: serves the repo
  checkout, real media fixtures, `/gone/*` → 410, `/bogus/image.png` → 200
  HTML (wrong content-type), and a path-pattern `/apps/yolo/api/image`
  route that only matches when the URL path (sans query) equals it.
- `harness.html` — instrumented fixture page that loads the real
  `ada-chat-card.js`, wraps console methods, records resource errors,
  and exposes scenario drivers for chat_push payloads.
- `fixtures/assets/` — real png/gif/mp4/webm binaries (ffmpeg-generated);
  `fixtures/pages/target.html` + `download-note.txt` for click/download.
- `preview-bridge.mjs` — node24 driver with two modes:
  - `--scenario all` (default OpenChamber Preview path): authenticates to
    the local `openchamber.service` (`127.0.0.1:3000`), registers as the
    preferred browser client over the SSE control plane, and serves
    `browser.open` / `browser.snapshot` / `browser.capture` /
    `browser.resize` actions from headless Chrome (Playwright, resolved
    via `PLAYWRIGHT_MODULE` or `~/.local/playlive/node_modules/playwright`).
  - direct Playwright mode for iteration without the control plane.
- `evidence/` — durable run output: `results.json` + `latest.json`
  (14 scenarios, verdict PASS, `failed=[]`), `.openchamber/screenshots/*`
  (14 captures taken through the Preview control plane), `shots/*`.
- `docs/ssot/jobs/ada/2026-11-24-ada-chat-card-preview-harness.yml` — job trail.

## Result

All acceptance criteria met:

- Fixture coverage: image-only, video-only, mixed, empty, broken
  (410/expired + wrong-content-type), and non-http `chat_push` inputs —
  plus text-URL rendering, stream re-render, click-to-open, download
  behavior, suite-all, and 390×844 mobile viewport. 14/14 PASS.
- OpenChamber Preview inspected the rendered element via
  `browser.snapshot`/`browser.capture` on every scenario.
- Browser console clean: expected broken-asset errors are classified by
  failing URL (`msg.location().url`, since Playwright console resource
  errors carry the page URL in the message text); `unexpectedProblems`
  excuses only `/gone/`, `does-not-exist`, `/bogus/` matches plus
  correlated bare "Failed to load resource" lines.
- No HA production deployment; nothing pushed.

## How to verify

```bash
cd tests/ha/ada-chat-card
~/.local/node24/bin/node preview-bridge.mjs --spawn-server --scenario all
# verdict: PASS — evidence in tests/ha/ada-chat-card/evidence
cat evidence/results.json | python3 -m json.tool | head -40
```

Direct Playwright mode (no OpenChamber service needed):
`node preview-bridge.mjs --spawn-server --scenario all --direct` (see
README for flags). Requires `openchamber.service` active on
`127.0.0.1:3000` for the Preview path and a Playwright install
(`PLAYWRIGHT_MODULE` or `~/.local/playlive/node_modules/playwright`).

## Lessons

- Playwright console resource errors put the page URL in `msg.text()`;
  the failing asset URL is only in `msg.location().url` — classify
  expected-broken fixtures by location, not text.
- Repo `.gitignore` has a blanket `media/` rule — name fixture dirs
  `assets/` (or similar) or binaries silently never commit; verify with
  `git check-ignore` before claiming durability.
- `sed 's|fixtures/media|...|'` missed the `"media", "file.png"` join
  form in server.py — a rename needs a grep for every path spelling.
- OpenChamber Preview is drivable headlessly: SSE control plane on
  `127.0.0.1:3000` + `browser.open/snapshot/capture/resize` actions +
  headless Chrome via Playwright covers viewport resize, console capture,
  and popups/downloads without a visible browser.
