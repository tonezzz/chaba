# Dispatch outcome — wire voice dubbing into the cast path (attempt 2)

Card: `yt-voice-dub-mode` · 2026-11-23 · host mn01

## Context

The feature was already merged 2026-10-07 (`724240b884`) and re-verified by
Tony 2026-11-23. This re-dispatch existed because two prior attempts died on
provider rate-limits, not on work. The last live audit (tony-macbook,
20:34) confirmed the wiring intact and reported one real gap — then its
worktree was lost when the session exited 1. This run landed that fix.

## What changed

- **`scripts/ops/yt-live.sh`** (`dub_job`) — the `timeout 5400
  yt-vtt-dub.py` render now runs backgrounded with a watchdog subshell
  that polls the `.gen-<pid>` token every 10s. On supersede (newer cast or
  `stop` → `clean_dir` removes the token) it resolves the render's live
  pgid and `pkill -9 -g`s the render tree, then the `__dub` group. Before,
  the token was only checked *after* the render returned — a superseded
  dub burned edge-tts for up to 90min alongside the new run's dub.
- **`docs/ssot/jobs/yt-dub/2026-11-23-yt-voice-dub-supersede-watchdog.yml`**
  — job record: findings, the gap, the fix, verification, lessons.
- `docs/ssot/ssot.dev-system.assessment.yml` — auto-refresh committed
  separately (pre-commit hook rewrites it every commit).

## Key subtlety found by live testing

GNU `timeout` leads its **own** process group for the managed command —
the render tree does not share the `__dub` pgid. A naive
`pkill -g <__dub-pgid>` kills the worker but orphans the render (verified
empirically: first test run left `timeout`+render alive). The watchdog
therefore resolves `ps -o pgid= -p $dpid` at kill time and group-kills
*that*, then the worker group. Arming is gated on `pgid==$$` so a manual
`__dub` invocation can't group-kill a caller's process group.

## Spec coverage (all confirmed in tree)

1. `POST /cast` `voice` off|th|en → arg3/env; 400 otherwise — api.py:220
2. dub render off `subs.vtt`+`src.mp4` (or cached media), sidechain-ducked
   mix, codec-copy remux → `dub.m3u8` — yt-live.sh dub_job/cache_replay_dub
3. Latency choice (already documented): **mid-play upgrade** — subs cast
   at MIN_SEGS, TV re-pointed to `dub.m3u8` when ready; TTS failure →
   subs-only, never fails the cast
4. Cache key carries voice (`<base>.<voice>` entries, replay serves the
   right playlist; failed dub stores honest subs variant)
5. `/status` exposes `dub {voice, phase}` from `dub.state`
6. `voice=off` path byte-identical — all dub code gated on `VOICE != off`

## Verification

- `bash -n` + `py_compile` clean; SSOT validation passed on commit.
- Sandbox `__dub` runs (fake `YT_VTT_DUB`, stub ffmpeg, fake HOME):
  - normal: render → mux → `th:done`, `dub.m3u8`+`dseg` produced, upgrade attempted
  - supersede: gen removed mid-render → render tree SIGKILLed ~5s later
    (one 10s poll tick), `__dub` gone, `dub.state` frozen, zero dub artifacts
- API smoke on test port: `voice=fr|de` → 400, `TH` → normalized `th`,
  omitted → `off`, `/status` exposes `dub`.
- Not verified here (needs tony-dell): real edge-tts render + real TV
  upgrade — unchanged merged code path, only the render invocation changed.

## How to verify on tony-dell

```
curl -X POST localhost:8791/cast -d '{"q":"<yt url>","voice":"th"}'
curl localhost:8791/status   # dub.phase: rendering -> muxing -> done
```
Then cast a second video mid-dub — the first render should die within ~10s
(`pgrep -af yt-vtt-dub` on tony-dell).

lessons:
- GNU timeout leads its own process group for the managed command — the
  child tree does NOT share the caller's pgid; resolve the child's pgid
  live (`ps -o pgid= -p $pid`) before group-killing.
- `pkill -f`/`pgrep -f` patterns that appear in your own `bash -c`
  command line self-match and can kill your own shell — put monitors in
  a script file.
- Dispatch worktrees can be 10+ commits behind master at claim time —
  `git pull --rebase` before committing keeps the merge trivial when
  upstream only touches card YAML.
