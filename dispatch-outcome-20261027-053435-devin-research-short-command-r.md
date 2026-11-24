# Dispatch outcome — Short command recognition research (DEV-0484)

Card: `devin-research-short-command-recognition-d948ed`
Placement: per Tony's card answer 2026-10-26 — chaba repo, research +
prototype under `docs/`, host-agnostic.

## What landed

- **`docs/kb/short-command-recognition-research.md`** — the research
  doc, added to the existing kb research-doc structure
  (same pattern as `nest-portable-brains-research.md`,
  `cheap-agent-cascade.md`). Covers: problem framing; inventory of the
  three narrow recognizers already in-system (ada-pi `command_lane`,
  tg_relay trivial-gate, devnest-tg-command-router) plus the qwen3-asr
  STT lane feeding them; external design-space survey (hassil-style
  grammar, exemplar/embedding similarity, small router LLM, KWS
  engines, e2e SLU) with a comparison table; recommended gated
  T0→T1→T2 cascade reusing the cheap-agent-cascade rules; Thai/
  code-switch constraints; open research questions; cardable next
  steps.
- **`docs/prototypes/short-command/`** — working host-agnostic
  prototype (stdlib Python, zero deps): `scr.py` recognizer
  (T0 hassil-lite template matcher with `(a|b)`/`[x]`/`{slot}` syntax
  where whitespace compiles to `\s*` so unspaced Thai matches; T1
  char-3gram+token-Jaccard exemplar match with gray band, optional
  `SCR_EMBED_URL` embedding scorer; T2 optional `SCR_ROUTER_URL` local
  LLM router, schema-validated, silent-on-timeout), `commands.json`
  starter grammar (Hass*/Board*/MemoryCorrect/ControlStop/Greeting/
  Thanks, EN+TH), `recognize.py` CLI, `eval/run_eval.py` harness with
  `--sweep`, `eval/corpus.jsonl` (51 items), `README.md`.
- **`docs/ssot/jobs/voice/2026-10-27-short-command-recognition-research.yml`**
  — job record with results, open questions, next steps.
- **`docs/INDEX.md`** — KB index entry added.
- **OPS-0919 filed** (`scr-calibrate-t1-thresholds-on-real-tg-v-8ca63e`)
  — calibrate T1 thresholds on the real idc03 TG voice corpus; this is
  the gating next step before any surface integration.

## Result

Eval on the shipped corpus: **51/51 correct, 0 wrong-fires, 88%
deflection** — T0 resolved 38, T1 resolved 7 paraphrases (scores
0.66–0.88). This is a synthetic floor: real calibration against the
qwen3-asr transcript distribution is carded (OPS-0919). Code-switch
input ("เปิด the light") correctly falls through to escalation —
documented grammar gap, not a bug.

## How to verify

```sh
python3 docs/prototypes/short-command/eval/run_eval.py          # 51/51
python3 docs/prototypes/short-command/eval/run_eval.py --sweep  # thresholds
python3 docs/prototypes/short-command/recognize.py "กี่โมงแล้ว"
printf '%s\n' "status OPS-0846" "ปิดไฟห้องนอน" | \
  python3 docs/prototypes/short-command/recognize.py --stdin
python3 -c "import yaml; yaml.safe_load(open(
  'docs/ssot/jobs/voice/2026-10-27-short-command-recognition-research.yml'))"
```

No commits to master, no push, no deploy — work sits on the dispatch
branch/worktree.
