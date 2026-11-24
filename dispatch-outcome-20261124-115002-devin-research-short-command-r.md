# Dispatch outcome — short command recognition research (attempt 2)

**Card:** `devin-research-short-command-recognition-d948ed` (DEV-0484,
follow-up OPS-0919). **Branch:** `dispatch/20261124-115002-devin-research-short-command-r`,
commit `aa7fbe9a4e` — 6 files, all committed this time.

## Root cause of attempt-1 failure (fixed)

Attempt 1 (2026-10-27) reported all deliverables landed, but merge
`fad1c13f` contained **only `docs/INDEX.md`** — the 9 real files were
left uncommitted in the old worktree ("worktree kept: dirty — 9
uncommitted file(s)") and lost. merge-sweep then auto-closed the card
on card-evidence checks without verifying the claimed paths exist —
a false-positive close. This attempt committed every artifact
explicitly; `docs/INDEX.md`'s dangling link now resolves.

## What was delivered

- `docs/kb/short-command-recognition-research.md` — design-space
  survey (pre-STT KWS/ASR-free/grammar-ASR vs post-STT cascade),
  in-system inventory (command_lane/systemone, tg_relay trivial_gate,
  devnest-tg-relay production T0, ada-stt lane, HA Gemini Live), and a
  recommended gated T0→T1→T2→T3 cascade with per-lane placement.
- `docs/prototypes/short-command/` — stdlib-only recognizer:
  `recognizer.py` (T0 phrase table + anchored operand-gated patterns;
  T1 char 3-5-gram TF-IDF cosine with accept/gray/reject zones, margin
  gate, operand gates, vetoes), `corpus.jsonl` (68 EN/TH items, hard /
  `t2:` soft / pass classes), `eval/run_eval.py` (report, `--json`,
  `--sweep` threshold frontier — the exact interface OPS-0919 expects).
- `docs/ssot/jobs/voice/2026-11-24-short-command-recognition-research.yml`
  — job record incl. attempt-1 postmortem.

## Result

`python3 eval/run_eval.py`: **0 wrong-fires**, **90.2% deflection**
(46/51 commands claimed at T0/T1; 5 soft commands correctly escalate
to T2). `--sweep`: accept ≥0.38 is the lowest zero-wrong-fire point;
default ships 0.42. Key finding: wrong-fires are specification bugs
(operand gates, vetoes like `ช่วย<verb>`/`status of <non-card>`, Thai
device-noun gate for bare เปิด/ปิด), not similarity bugs — structure
fixed all four initial wrong-fires where thresholds could not.

## How to verify

```bash
cd docs/prototypes/short-command
python3 eval/run_eval.py          # expect: 0 wrong-fires, 90.2%
python3 eval/run_eval.py --sweep  # frontier table
ls docs/kb/short-command-recognition-research.md
```

After merge: `git log origin/master -- docs/kb/short-command-recognition-research.md`
should show this commit's files — the check attempt 1 skipped.

lessons:
- dispatch close-out verified card comms, not artifact existence — merge-sweep should check claimed paths landed before auto-closing "done"
- worktree "kept: dirty — N uncommitted file(s)" after merge means deliverables were LOST; treat that comms line as a failure signal, not housekeeping
- Thai has no word boundaries: \b-based regex and token matching fail silently — char n-grams + operand-gated prefixes are the workable shape
- operand-defined intents (explain/approve/device-TH) need the operand required at EVERY tier, not just T0 — "explain how DNS works" and "ปิดเสียง" (mute) are the canonical traps
- follow-up cards may pin expected file paths (OPS-0919 wanted eval/run_eval.py --sweep) — check kanban for dependents before choosing artifact layout
