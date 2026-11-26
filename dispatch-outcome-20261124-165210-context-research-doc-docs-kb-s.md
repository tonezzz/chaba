# dispatch-outcome — scr-calibrate-t1-thresholds-on-real-tg-v-8ca63e

## What changed

**Recovered lost work first:** the parent card's prototype
(`docs/prototypes/short-command/` + `docs/kb/short-command-recognition-
research.md` + job record) was never committed — the 2026-10-27
tony-macbook session left it staged-but-uncommitted in its dispatch
worktree. Pulled it verbatim via ssh into this worktree; it now lands
with this card's merge (added missing `title:` to the job yml for the
SSOT hook).

**Calibration (the card's actual work):**

- Built `docs/prototypes/short-command/eval/corpus-tg-qwen.jsonl` and
  `corpus-tg-ref.jsonl` — the 28 real TG voice clips from the STT lane
  eval assets (idc03 `ada-voice-corpus/tg/` manifest × idc02
  `~/audio-cpp-eval/` refs-all + results-qwen3-asr-q8). `text` = qwen3
  hyp (production STT output) / Gemini ref respectively; sources kept
  in `eval/tg-voice-src/`.
- Labeled all 28 `no_match` after reviewing each against
  `commands.json` intents: **zero in-grammar short commands exist in
  real TG voice traffic** (status questions, transcript tests, voice-
  dub requests, EN/TH/DE/TL code-switch, 3 empty-STT clips).
- Ran `eval/run_eval.py --sweep` (gained `--corpus PATH`) plus a finer
  threshold scan with thresholds disabled to get raw score
  distributions.

## Results

- Max non-command T1 score: **0.216** (synthetic EN negative);
  real TG max **0.163**. Min true-command T1 score: **0.615**.
- Wrong-fire rate on real data: **0/28 = 0%** on both qwen3 and ref
  corpora at every threshold ≥0.25; 2 synthetic wrong-fires appear only
  at accept≤0.20.
- Deflection on real TG voice: 0% — correct, there is nothing to
  deflect; the recognizer's job on this traffic is purely not firing.
- qwen3 transliteration drift ("Claude"→"crowd", "Telegram"→"เทเลกาน")
  lowers similarity, never fabricates command likeness. T0 fired 0
  times on real data.

## Recommendation (written into the research doc)

- **accept=0.40, gray_lo=0.25** (defaults updated in `scr.py`, was
  0.55/0.45) — mid-gap between worst non-command (0.216) and weakest
  true command (0.615); gray band reserves did-you-mean UX.
- **tg_relay first**, ada-pi `command_lane` second — anchored
  whole-message text maps 1:1 to SCR's grammar rule; command_lane sits
  on the live voice path behind a slow T2 endpoint.
- Caveat recorded: real-corpus command *recall* is unmeasured (no
  positives); 8 newer manifest clips lack refs — corpus needs a
  gen_refs + qwen3 re-run to grow.

## Files

- `docs/kb/short-command-recognition-research.md` — new "Real-corpus
  calibration" section; research Q1 resolved.
- `docs/prototypes/short-command/` — full prototype + eval corpora.
- `docs/ssot/jobs/voice/2026-11-24-scr-t1-threshold-calibration.yml`
  — trail; `2026-10-27-…research.yml` — recovered job record.

## Verify

```sh
cd docs/prototypes/short-command
python3 eval/run_eval.py --corpus eval/corpus-tg-qwen.jsonl   # n=28 acc=1.0 wrong=0
python3 eval/run_eval.py --corpus eval/corpus-tg-ref.jsonl
python3 eval/run_eval.py --sweep
```

Commit: `d14f6b18b9` on this dispatch branch (not pushed).

lessons:
- Dispatch sessions can leave deliverables staged-but-uncommitted on the runner host — before declaring referenced files missing, ssh to the origin host's dispatch worktree and check `git status` there.
- `git log --all -- <path>` on this repo is extremely slow (huge history); prefer `git ls-remote`/branch listing + targeted `git ls-tree`.
- SSOT pre-commit hook requires `title:` in docs/ssot/jobs/*.yml — recovered files may predate the rule.
