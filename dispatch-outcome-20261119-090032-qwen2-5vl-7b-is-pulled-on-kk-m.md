# dispatch outcome — kk-mac-vision-lane-eval (2026-11-19 09:00)

## What changed

Built `scripts/bench/vision-qa/` — a vision benchmark for qwen2.5vl:7b on
kk-mac, following the `scripts/bench/card-judgment/` harness pattern:

- `imglib.py` — dependency-free canvas: stdlib PNG writer (zlib), shapes/
  gradients, embedded 5x7 bitmap font, and defect effects (box blur,
  Gaussian noise, banding, rotated semi-transparent watermark). No PIL —
  runners don't have it.
- `build_corpus.py` — regenerates `images/*.png` + `corpus.jsonl`:
  **20 deterministic cases**
  - stock lane (13): 4 description-match (yes), 3 mismatch (no),
    4 defect-present (blur / watermark / noise / banding → yes),
    2 clean (no)
  - ui lane (7): 4-way triage — ok ×2, error_state ×2, layout_bug ×2,
    empty_state ×1
- `score.py` — sends each case's image (base64) + question to a VLM,
  parses a strict JSON `{"answer": ...}` verdict with prose fallback and
  label normalization, then scores overall/per-lane/per-kind accuracy,
  defect recall+specificity, confusion, latency. Entities: `ollama`
  (native `/api/chat` with `images=[b64]` — the reliable image path),
  `openai` (`/v1/chat/completions` with `image_url`, for LiteLLM),
  `mock-oracle` (harness smoke test). Same smctemp thermal-pause gate as
  card-judgment's score.py.
- `kkmac_eval.sh` — same fail-closed gates as card-judgment
  `kkmac_eval.sh`: ssh `kkkakk@kk-mac`, `ollama /api/tags` over ssh,
  corpus presence; prefers `qwen2.5vl:7b` then other pulled VLMs;
  writes `run-kkmac-<model>.{md,json}` next to the corpus.
- `docs/ssot/jobs/devnest/2026-11-19-kkmac-vision-qa-bench.yml` — job
  record (corpus shape, provisional thresholds, run/verify steps).

## Result

**Verdict: pending — kk-mac is offline.** Tailnet shows kk-mac last seen
~13h ago (member device, no remote wake); `ssh` times out and the
eval's own gate correctly aborts `exit=2` without running anything.
The task's "run when kk-mac is awake" clause applies — the harness is
ready to fire.

Provisional "usable lane" bar (declared in the report + job record):
overall ≥0.80, stock lane ≥0.80, defect recall ≥0.75, ui lane ≥0.70,
zero parse failures.

## How to verify / run

```bash
python3 scripts/bench/vision-qa/build_corpus.py          # rebuild corpus
python3 scripts/bench/vision-qa/score.py --entity mock-oracle   # all-PASS
scripts/bench/vision-qa/kkmac_eval.sh                    # real run on kk-mac
```

Verified this session: corpus builds (20 PNGs, all visually inspected —
scenes are clearly recognizable); mock-oracle run scores all-PASS with
correct confusion/per-kind metrics; `parse_answer` handles JSON, fenced
JSON, prose, and label aliases; `kkmac_eval.sh` fails closed at the ssh
gate while kk-mac is down.

## Caveats

- Synthetic images give exact gold labels and a reproducible offline
  corpus, but test schematic scene recognition, not photographic nuance.
  If qwen2.5vl passes, replay real campaign renders
  (gdrive:ada-nest/adobe-stock, e.g. AS-2026-11-05-REMOTE-WORK-001)
  through the same scorer before trusting it on production assets —
  that was already the planned next gate in adobe-stock-kk-mac-render-poc.
- Card file `kk-mac-vision-lane-eval` is not present in this worktree's
  `docs/ssot/kanban/cards/` (board-api comment posted instead; card
  presumably created live since last sync).

## Board

Two comments posted to `kk-mac-vision-lane-eval` via board-api
(start + built/gated status). No requests raised — this is a time-gate,
not a decision. No pushes.
