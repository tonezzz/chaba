# dispatch outcome — nest-percussion (verify + pitch-from-health)

## What I found

The percussion stack was **already built and live** — this card's work
landed 2026-10-10 (commit `791af4cb58`) and was extended by the done
`percussion-music-layer` card. What remained was verification plus one
spec gap. Verified live state on tony-dell:

- `ops-percussion.timer` armed, oneshot every 60s, `ops-percussion.service`
  exits SUCCESS each run (`bpm=130 alerts=4 hosts=9` at last run).
- `state.json` served at
  `https://tony-dell.taila0626a.ts.net/apps/percussion/state.json`,
  observed 11–52s stale across probes — inside the <60s done-condition.
- Page `…/apps/percussion/` → HTTP 200; headless Chrome rendered the
  live stat line (`bpm 135 · 8/9 up · 3 failing · alerts: postgres,
  gpu-queue, yomi-api · polyphia+bright [guitar]`) with zero JS errors.
- `GET /api/input-bridge/percussion` → 200, live control
  `{style:polyphia, mood:bright, instruments:[guitar]}`.

## What changed (commit `a2f138a840` on the dispatch branch)

- `stacks/web/public/apps/percussion/app.js` — added `hostDetune(h)`:
  pitch multiplier `1 + clamp(load1m,0..30)/30*0.05 + state nudge`
  (degraded +2%, error +5%, unknown −1%), threaded as `det` through
  kick/snare/tom/hat/shaker. This is the literal "pitch from health"
  half of the spec — previously only accents/velocity reflected health.
- `stacks/web/public/apps/percussion/index.html` — added
  `mobile-web-app-capable` (the apple- variant is deprecated; Chrome
  logged it during the headless check). iPad-first polish.
- `stacks/web/public/apps/apps.yml` — percussion added to the
  System & Ops group + flat entry; it was URL-reachable but missing
  from the `/apps/` launcher.
- `scripts/ops-percussion-check.mjs` — **new repo-side check** (vm
  context, stubbed DOM+WebAudio, no browser/hardware). Defaults to
  fetching the LIVE state.json; accepts a fixture path arg. Style
  mirrors `vcast-cast-check.mjs`.
- `docs/ssot/jobs/nest/2026-11-24-percussion-verify.yml` — trail doc.

## Result / verification

`node scripts/ops-percussion-check.mjs` → **15/15 PASS**:
state fresh, engine loads live state, bpm mapped (130), tap-to-start
engages scheduler, 544 hits over ~17 bars all on the 16th-note grid,
error=accent+stutter (2→4 osc hits), degraded=quieter (0.35<1.00),
unknown keeps its voice, alerts=crash on downbeat only, pitch rises
with load (150→157.5Hz) and on error, step duration follows bpm.

Done-condition verdict: **all three legs PASS** — page loads over the
tailnet, state.json <60s stale (timer-driven), audible groove reflects
live state (proven by the check toggling state fixtures; the browser
render confirms live values reach the page).

## Deploy note

Dispatch mode — nothing pushed or deployed. `index.html` cache-busts
`app.js` with `?v=Date.now()`, so the detune lands on the next hourly
`chaba-repo-sync` pull of `chaba-tony-dell` on tony-dell. The state
feed and timer are unaffected.

## lessons

- vm-context gotcha: top-level `const`/`let` in a script do NOT attach
  to the sandbox object — pull handles with a second `runInContext`
  in the same context.
- When stubbing AudioParams, only record `setValueAtTime` on params
  flagged as gain — otherwise `frequency.setValueAtTime(150)` pollutes
  the velocity log.
- `node(kind)` factory closures must reference the node object (`n`),
  not the `extra` arg — properties assigned after creation aren't in
  `extra`.
- Percussion was already live when this card dispatched; always probe
  the live surface before rebuilding — the real gap was one spec line
  (pitch-from-health), not the whole page.
