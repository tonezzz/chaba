# Dispatch outcome — audit-oc-denied-tool-muijr5b4

## What the card asked

Auto-filed audit card: OpenCode session `ses_e75215d71ffepqrRAimUiJR5b4`
("Supervised OpenCode lane pilot health report") had **113 denied tool
calls (all `bash`)** per the 2026-11-07 session audit. Investigate and
classify.

## What I found

Fully attributed from committed repo evidence
(`evals/opencode-lane/reports/2026-11-07-session-audit.json`):

- Session = the **first nemotron attempt** on card `devnest-fl-pilot-health`
  (idc02, 2026-10-30 10:33–10:43 ICT, agent `ops-readonly`, model
  `litellm/or-free-nemotron-nano`, wall 614.7s, 131 steps).
- All 113 denials are **rule-based bash-allowlist denies** from the
  ops-readonly profile. The 26 unique denied commands are the weak model
  probing outside the allowlist: `find`/`grep` over the worktree and
  `/etc/systemd`, `cat`/`awk` on `/proc/*`, piped `ls|head`,
  `systemctl --failed`, and `echo '{...}'` attempts to write the artifact
  via bash — the emit-vs-write failure mode noted on the parent card.
- **Enforcement held**: 0 mutations, 0 artifacts, 0 errors, nothing
  written. 10 bash calls did pass the allowlist.
- This is the exact incident behind **OPS-0999
  (`runner-dispatch-no-timeout`)**: unbounded wall-clock (614.7s vs
  fixture `timeout_s=420`) + no denial-streak breaker on headless
  `doom_loop=ask`. Both fixes merged 2026-11-24
  (`scripts/devnest/opencode_stream_guard.py`, RuntimeMaxSec on lane
  units).
- Parent card recovered: attempt 3 (`or-gemini-3.5-flash`) passed the
  held-out verifier, auto-merged, auto-closed 2026-10-30.

## Deliverable

`docs/ssot/jobs/devnest/2026-11-24-opencode-denied-tool-muijr5b4-audit.yml`
— full finding, denial semantics, safety verdict (PASS), verification.

## Verdict

PASS — denials are the permission layer working as designed against a
weak model; the systemic gaps (no timeout, no denial breaker) were
already fixed under OPS-0999. No further action needed on this card.

## How to verify

- `python3 -c "import json; d=json.load(open('evals/opencode-lane/reports/2026-11-07-session-audit.json')); print([s for s in d['sessions'] if s['session_id']=='ses_e75215d71ffepqrRAimUiJR5b4'][0]['tools'])"`
- `cat docs/ssot/jobs/devnest/2026-11-24-opencode-denied-tool-muijr5b4-audit.yml`
- Compare with `docs/ssot/jobs/devnest/2026-11-24-runner-dispatch-bounded-units.yml`

lessons:
- Audit short-IDs in `denied_calls` are per-session; the committed
  2026-11-07-session-audit.json in `evals/opencode-lane/reports/` now
  carries full denied_call inputs — attribution no longer needs host DB
  access (unlike the AUD-0944 era).
- The nemotron denial-loop incident (this card) is the same event
  OPS-0999 cites; cross-check `runner-dispatch-no-timeout` card comms
  before re-diagnosing "new" denial storms.
- opencode_stream_guard resets its denial streak on ANY completed tool
  call — interleaved allowlisted calls can keep a streak under
  max_streak=10; RuntimeMaxSec is the real wall-clock backstop.
