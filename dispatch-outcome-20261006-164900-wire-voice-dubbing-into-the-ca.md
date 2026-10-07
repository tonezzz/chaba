# Dispatch outcome — wire voice dubbing into the cast path

Card: `yt-voice-dub-mode` · 2026-10-06

## What changed

- **`scripts/ops/yt-live-api.py`** — `POST /cast` accepts optional
  `voice` (`off|th|en`, default `off`, HTTP 400 otherwise) and passes it
  to `yt-live.sh` as positional arg 3. `GET /status` gains a `dub`
  object (`{voice, phase}`) parsed from `dub.state`
  (`<voice>:<phase>` — rendering|muxing|done|failed|skipped). Added
  `YT_LIVE_APP`/`YT_LIVE_MCACHE` env overrides for testability.
- **`scripts/ops/yt-live.sh`** — voice param via arg3 / `YT_LIVE_VOICE`.
  With captions present, a detached `__dub` worker (setsid, same pattern
  as `__finalize`) runs `yt-vtt-dub.py` against `subs.vtt` + `src.mp4`
  (or the cached media on replay), producing `dub.mp4` with the existing
  sidechain-ducked mix; it then remuxes codec-copy to `dseg_*.ts` +
  `dub.m3u8` and re-points the TV. Cache layer is voice-aware: lookup
  matches the requested voice, dubbed entries carry `dub.m3u8` and land
  under `<vid>.<srclang>.<langs>.<voice>`, replay serves `dub.m3u8` for
  voice entries and `media.m3u8` otherwise, and a voice request that
  only finds a subs-only entry replays it instantly and upgrades
  mid-play while the `.voice` variant fills in. `GEN_TOKEN` is created
  unconditionally so detached workers survive orchestrator exit.
- **`docs/kb/home-assistant/tv-casting-runbook.md`** — voice-mode API,
  mid-play upgrade strategy, and voice cache keys documented.
- **`docs/ssot/jobs/yt-dub/2026-10-06-yt-voice-dub-mode.yml`** — job
  record with decision, metrics, and lessons.

## Key decision

**Mid-play upgrade** (chosen over gating the cast on dub completion):
edge-tts synthesis is far slower than the transcode, so the subs-only
HLS casts at `MIN_SEGS` as usual while the dub renders detached; when
`dub.mp4` lands, the worker remuxes it (seconds) and re-casts
`dub.m3u8` — playback restarts at 0 dubbed. The `.cast-sent` marker
defers the upgrade until the subs cast has actually gone out, and the
run's `.gen-<pid>` token is the "still the current run" gate — a newer
cast or `stop` removes it via `clean_dir` and workers exit before
touching new-run artifacts. Any TTS/mux failure writes `<voice>:failed`
and the subs cast continues untouched. `voice=off` runs the
byte-identical pre-change path (no dub worker, `media.m3u8`).

## Result / verification (sandboxed: `YT_LIVE_APP`/`YT_LIVE_MCACHE`,
HA endpoint `http://127.0.0.1:9` — no real TV)

- Fresh `voice=th` cast of `CSKlIsz9SZo` (94s EN→TH): subs HLS cast at
  MIN_SEGS, dub rendered detached, `dub.m3u8` + 22 `dseg_*.ts` remuxed,
  TV re-pointed mid-play; cache entry `CSKlIsz9SZo.en.th.th` with
  `meta.voice=th`.
- Replay `voice=th` → `dub.m3u8` instantly (no TTS); `voice=off` and
  omitted → `media.m3u8` unchanged; bogus voice → exit 2 / API 400.
- Off-cache + `voice=th`: subs replay immediately, dub renders off
  cached `src.mp4`, upgrade + new `.th` cache entry created.
- Forced TTS failure (`YT_VTT_DUB=/bin/false`): `dub.state=th:failed`,
  subs cast continues, no `dub.m3u8`, no false voice cache entry.
- API on a test port: `/health` ok, `/status` reports
  `{"dub":{"voice":"th","phase":"rendering"}}` live.
- `bash -n` + `python3 -m py_compile` clean; shellcheck not installed.
- Bugs found & fixed along the way: `cache_replay` wiped the current
  run's gen token (detached workers self-aborted) — now preserves it;
  replay-path dubs lacked `GEMINI_API_KEY` — `dub_job` sources the
  secrets file itself; off-variant entries could carry a truncated
  `dub.m3u8` and fail validation — finalize strips dub artifacts for
  off variants.

## Not done / follow-ups

- Real TV playback of the upgrade was not exercised (dead HA endpoint);
  first live cast verifies the re-point lands on the TV.
- `~/.local/bin` copies were NOT refreshed (deploy needs approval) —
  run `scripts/ops/yt-pipeline-install.sh` after merge so the live :8791
  api serves the voice field.
- Sandbox only; no commits, no push, no deploy.

## Summary

Voice dubbing is wired into the cast path end-to-end: `POST /cast`
accepts `voice=off|th|en` (default off, 400 otherwise) → `yt-live.sh`
arg3/`YT_LIVE_VOICE`; with captions present a detached `__dub` worker
renders `dub.mp4` via `yt-vtt-dub.py` in parallel with the transcode,
remuxes it to `dub.m3u8`/`dseg_*.ts`, and re-points the TV mid-play
(chosen over gating the cast — TTS is far slower than transcode, so
subs play first and the dub swaps in); TTS/mux failures leave the subs
cast untouched. Dubbed variants cache independently under
`<vid>.<srclang>.<langs>.<voice>` and replay serves the right playlist
per requested mode; `/status` exposes `dub {voice,phase}`. Verified
end-to-end in a sandbox (fresh th dub + mid-play upgrade, dubbed and
subs replays, off-cache upgrade path, forced-failure fallback, API
validation); real-TV playback and the `yt-pipeline-install.sh` refresh
of `~/.local/bin` remain as deploy-side follow-ups. Deliverables: the
two pipeline scripts, a runbook note, and
`docs/ssot/jobs/yt-dub/2026-10-06-yt-voice-dub-mode.yml`.
