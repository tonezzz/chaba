# Dispatch outcome — gev-map: honest-fail on every pane type (2026-11-23)

**Card:** `gev-map` (MED-0135) · **Lane:** chaba dispatch worktree ·
**Commit:** `3e49ce0402` on `dispatch/20261123-155342-gods-eye-view-app-work-held-re`
(not pushed — gods-eye-view repo still HELD: no pushable remote, not in
dispatch-repos.conf; all work staged inside chaba + the ada-voice drop zone).

## What changed

**vcast display — per-pane honest-fail (`stacks/web/public/apps/vcast/index.html`, `sw.js` v13→v14)**
- New `.pfail` overlay per pane (static pane0 + `makePane` template);
  `paneFail(p,msg,quiet)` draws it and reports `state=pane-fail`
  (deduped); `paneOk` clears on real content, new cast, or teardown.
- **video**: element `error` on the non-recovering path →
  `video failed — <MEDIA_ERR_* reason>`; 20s no-frames stall watchdog
  (skipped while an HLS retry is armed); HLS panes veil at retry #5
  ("stream offline — still retrying", quiet — `hls-retry` stays the
  authoritative state).
- **img**: `onerror` → overlay (existing HUD/toast/state kept); `onload` clears.
- **iframe**: 25s no-`load` watchdog → "page did not load"; on load,
  `armFrameProbe` polls same-origin `contentWindow.__gevHonestFail /
  __gevRenderOk` every 3s; a `message` listener accepts
  `{type:"gev-honest-fail"|"gev-honest-ok"}` cross-origin — the channel
  the GEV watchdog posts to.

**GEV — watchdog + post-build patcher**
- `stacks/web/public/apps/gev/honest-fail.js` (new, vendored, no deps):
  no `.cesium-widget` canvas after 25s → `#gev-honest-fail` overlay
  naming the reason (with captured WebGL/Cesium error hint);
  `webglcontextlost` → overlay, `webglcontextrestored` → clears. Sets
  `__gevHonestFail`/`__gevRenderOk` and postMessages the host frame.
- `scripts/gev/patch-gev-dist.sh` (new): codifies the AGENTS.md
  post-build patches — quote-bounded `"/api/`+`"/models/` →
  `/apps/gev/*` on `assets/*.js`, `msaaSamples:4` → iPad/iPhone/iPod UA
  ternary **(the iPad crash patch, kept)**, honest-fail.js inject +
  stage. Idempotent; `--check` verifies a dist, `--self-test` runs a
  fixture (incl. absolute-URL non-mangling). **Applied to the staged
  dist** — both it and the live bundle were raw unpatched (live
  `msaaSamples:4` verified via curl), so next deploy lands the patches
  prod never got.

**ada-voice drop 20 (`integrations/ada-voice/`)**
- `tests/scenarios-live/gev_pane_honest_fail.yaml` — replaces upstream:
  layer-1 `http_check` guards (vcast wiring for every pane type, GEV
  watchdog served, bundle keeps `msaaSamples:/iPad` + no `msaaSamples:4`),
  layer-2 `vcast_display` driver (claim → typed `pub` play/image/nav →
  `report` pane-fail → `/displays` regex), layer-3 original honesty turns.
- `scripts/scenario-live.pane-pub.patch` — `pub` gains `type:`/`pane:`,
  new `report` action emitting display state. Verified `git apply`
  clean on upstream `scripts/scenario-live.py`.
- `README.md` — drop 20 documented with install steps.

**Docs/trail** — `AGENTS.md` GEV build section now points at
patch-gev-dist.sh + honest-fail contract; `ssot.apps.vcast.yml`,
`ssot.apps.gev.yml` updated; job trail
`docs/ssot/jobs/gev/2026-11-23-gev-pane-honest-fail.yml`; repo-side check
`stacks/web/input-bridge/gev-honest-fail-check.mjs` (30 asserts).

## Result / how to verify

- `node stacks/web/input-bridge/gev-honest-fail-check.mjs` → **30/30 PASS**
- `scripts/gev/patch-gev-dist.sh --self-test` → SELFTEST-OK;
  `--check stacks/web/public/apps/gev` → fully patched
- SSOT validation + prose-smell clean; scenario YAML parses (18 turns).
- Not verified live (approval-gated): DOM overlay on a real display and
  the scenario run itself — needs the web stack deployed + drop 20
  installed in `~/CascadeProjects/ada-voice` (see README §Drop 20) then
  `python3 scripts/scenario-live.py tests/scenarios-live/gev_pane_honest_fail.yaml`.

lessons:
- The staged GEV bundle AND the live served bundle were both raw
  unpatched dist — "post-build patch in AGENTS.md" was documented but
  never applied to either; codify+verify, don't document-and-hope.
- iframe `load` fires even for X-Frame-Options refusals — a load
  watchdog only catches dead targets; in-frame failure needs a probe
  (same-origin flag) or postMessage channel.
- hls.js attaches a `blob:` URL to video.src — pick the remembered
  stream URL for failure surfaces, not element.src.
- The dispatch worktree's pre-commit hook regenerates
  ssot.dev-system.assessment.yml — leave that unrelated churn
  uncommitted.
