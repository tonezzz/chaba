# Dispatch outcome — wire voice dubbing into the cast path (re-run)

Card: `yt-voice-dub-mode` · 2026-11-23 · attempt 2 (prior run died on a
provider rate-limit — exit=1 infra failure, not a code defect)

## What I found

The voice-mode selector was already implemented and merged on
2026-10-07 (`724240b884`), and this worktree (tracking origin/master)
contains it intact. I audited the merged code against every spec item
after the post-merge `yt-vtt-dub.py` changes (qc gate, fix-map,
sentences, diarize, DUBFIT metrics):

- `POST /cast` accepts `voice` (`off|th|en`, default `off`, HTTP 400 on
  anything else) → `yt-live.sh` arg3 / `YT_LIVE_VOICE`
  (`scripts/ops/yt-live-api.py:220-224`).
- `yt-live.sh` spawns a detached `__dub` worker when `voice != off` and
  captions exist; it runs `yt-vtt-dub.py` against `subs.vtt` + `src.mp4`
  (or cached media on replay), remuxes the sidechain-ducked `dub.mp4`
  to `dub.m3u8`/`dseg_*.ts`, and re-points the TV mid-play
  (`dub_job`, `scripts/ops/yt-live.sh:316-379`). Latency choice —
  mid-play upgrade — is documented in the script, runbook, and the
  2026-10-06 job record.
- Media cache is voice-aware: dubbed entries land under
  `<base>.<voice>` with `meta.voice`, lookup matches the requested
  variant, replay serves `dub.m3u8` for voice entries and
  `media.m3u8` for off; a voice request with only a subs entry cached
  upgrades mid-play while the `.voice` variant fills in.
- `/status` exposes `dub: {voice, phase}` parsed from `dub.state`.
- `voice=off` is byte-identical: this session's diff touches only
  `dub_job` internals, which never run for `off`.
- edge-tts failure → `<voice>:failed`, subs cast continues (verified
  path; `dub_job` returns 0 on every failure branch).
- All `dub_job` flags still exist in the current `yt-vtt-dub.py`
  CLI (`--qc`, `--fix-map` comma-paths, `--sentences`, `--en-vtt`,
  `--no-compress`); the mux contract (dub over sidechain-ducked
  original → mp4) is unchanged; QC report lands at `dub.qc.json` as
  `clean_dir` expects.

## What I changed

`scripts/ops/yt-live.sh` — `dub_job` only: the edge-tts render now runs
under a **gen-token watchdog**. Previously the render was a single
`timeout 5400` call with the `.gen-<pid>` liveness check only *after* it
finished — a cast superseded mid-render left the stale dub synthesizing
for up to ~90 min, competing with the new run's dub for the flaky
edge-tts lane (the exact parallel-load failure mode the card calls out).
The render is now backgrounded; a sibling subshell polls the gen token
every 30 s and kills the render on supersede; `wait || drc` preserves
the original exit-status → mux/failed-state semantics. `voice=off` is
untouched.

Testing caught a real bug in my first version: the kill branch sits
after the final `||` of `[ -f "$gen" ] || { ... }`, where `set -e` is
*active inside the braces* — bare `pkill` returns 1 on no-match and
silently killed the watchdog itself (render ran the full 60 s in the
harness). All kill-branch commands are now `|| true` guarded, with a
comment marking the trap.

## Verification

- `bash -n yt-live.sh` clean; `py_compile` on api + dub clean.
- API smoke (test port 18791, sandbox `YT_LIVE_APP`/`YT_LIVE_MCACHE`):
  `/health` ok; `/status` exposes `dub`; `/cast` → 400 on missing `q`
  and `voice=fr`; `voice=TH` normalized to `th`; omitted → `off`.
- Watchdog harness (`set -euo pipefail`, isolated): gen alive → rc=0
  mux path; child exit 3 → `drc=3` failed-state; gen removed mid-render
  → child killed ~2 s later (rc=143), silent exit, no orphaned
  processes.
- Full sandbox e2e / real edge-tts render not possible on this host
  (no ffmpeg/yt-dlp/edge-tts venv) — the merged implementation was
  already e2e-verified on 2026-10-06 (see
  `dispatch-outcome-20261006-164900-wire-voice-dubbing-into-the-ca.md`
  and `docs/ssot/jobs/yt-dub/2026-10-06-yt-voice-dub-mode.yml`).

## Not done / follow-ups

- Real-TV verify (card `verify:` criterion) still needs the
  `yt-pipeline-install.sh` refresh of `~/.local/bin` on tony-dell —
  deploy gate, requires approval. Once deployed: cast a cached video
  with `voice=th`, confirm the mid-play upgrade lands on the TV.
- Job trail: `docs/ssot/jobs/yt-dub/2026-11-23-yt-voice-dub-mode-watchdog.yml`.

## Summary

The voice-dub cast path was already merged and spec-complete; this run
audited it against the post-merge `yt-vtt-dub.py` changes (all
compatible), smoke-tested the API voice surface, and fixed the one
real gap found: superseded dub renders now get killed within ~30 s by
a gen-token watchdog instead of burning flaky edge-tts for up to 90
min alongside the new run's dub. `voice=off` remains byte-identical;
TTS failure still falls back to the subs-only cast. Remaining gate is
deploy-side: refresh `~/.local/bin` on tony-dell, then real-TV verify.

lessons:
- "set -e applies inside a { } group that follows the final || of an AND-OR list — 'cmd || { pkill ...; }' dies silently when pkill returns 1; guard every command in such groups with || true."
- "Gate detached workers DURING long subprocess calls, not only after — a sibling watchdog subshell polling the gen token every 30s kills superseded edge-tts renders."
- "procps pkill/pkill -P with no pattern returns 1 on no-match (not usage error) — usable, but only behind || true under set -e."
