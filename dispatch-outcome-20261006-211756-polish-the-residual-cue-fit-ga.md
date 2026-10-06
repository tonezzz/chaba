# Dispatch outcome — yt-voice-dub-cuefit (2026-10-06)

All three card lanes landed and verified on the corpus slices.

## What changed (commit 6ae91da5 on the dispatch worktree branch)

- **`scripts/ops/yt-vtt-translate.py`** — new `--groups` mode: consumes a
  `yt-vtt-dub.py --dump-groups` table (`[{i,s,e,voice,en,th}]`) and writes a
  JSON array of per-group translations = the `--th-file` format. One Gemini
  call per `--batch` groups (default 20), model-chain retry, disk cache at
  `~/.cache/yt-live-subs/groups/<sha>.<lang>.json` keyed on
  prompt-version+lang+model+inputs. The prompt asks for conversational
  spoken Thai sized to each group's window in seconds. Fallback when no API:
  each group's cue-level MT `th` — degrades to prior behaviour, never silence.
- **`scripts/ops/yt-vtt-dub.py`**
  - `--dump-groups` now emits `e` (fit-window end = next group start) so the
    translator sees the real time budget.
  - `--th-auto`: runs the sibling translator on the in-memory group table —
    replaces the hand-written `--th-file` (an explicit `--th-file` still
    wins). The compress pass is skipped when group-level text supplies the
    spoken line (it's already window-sized).
  - `--rate-spread` (default ±0.10): each group resynths at
    `clamp(dur/window, max(global−spread,1.0), min(global+spread,max-rate))`
    in 5% steps — the single global rate no longer pins long groups; 1.4x
    atempo cap and shared lag budget unchanged.
  - `DUBFIT {json}` line per render (+ `--metrics-json PATH`): speech/window,
    global rate + applied band, atempo max/count (cap 1.4), clipped count,
    `lag_s` cumulative + `lag_max` worst-segment lateness, `ends_at`.
    Scenarios should gate on `lag_max` (the viewer-visible drift), not the
    cumulative sum.
  - Fixes: edge-tts retries back off 1.5s·n / 5 tries (parallel-synth 403
    rate-limits were silently dropping ~19% of groups); negative cue starts
    from `--offset` slices no longer inflate lag.

## Verification (all card targets pass)

| render | segments | rate applied | atempo | clipped | lag_max | ends_at |
|---|---|---|---|---|---|---|
| 4njFdBF_42I slice 20–200s, 3-voice cast, `--th-auto` | 37/37 | 1.00–1.05 | 1 seg @1.13 | 0 | 2.45s | 179.8/180 |
| The Egg 180s, `--th-auto` | 11/11 | 1.00–1.05 | 0 | 0 | 0.0s | 162.7/180 |
| The Egg baseline (cue-MT + compress) | 10/11 | 1.00–1.05 | 0 | 0 | 0.0s | 145.7/180 |

TH output is conversational register (auto: "คุณตายแล้ว…ไม่ต้องคิดมาก…ใครก็ตาย",
particles สินะ/แหละ/เถอะ) vs literal cue-MT. On the interview specimen, TH
speech is 142s in a 179s window — the ~1.4x overflow is gone without hand
editing.

## How to verify / review

- `grep '^DUBFIT '` on renderer stdout → parse JSON.
- Listen check: `apps/yt-live/dub-cuefit-4nj.mp4` and `dub-cuefit-egg.mp4`
  (staged into the served apps dir, HTTP 200 confirmed).
- Artifacts: `/tmp/cuefit/` — renders, `*-fit.json` DUBFIT dicts,
  `*-groups.json` dumps, `*-th.json` generated translations, `*-burn.vtt`.
- Runbook: `docs/ssot/jobs/yt-dub/2026-10-06-yt-voice-dub-cuefit.yml`.
- Note: `~/.local/bin` copies of the two scripts are NOT refreshed
  (yt-pipeline-install.sh not run — live-checkout mutation left for merge).
