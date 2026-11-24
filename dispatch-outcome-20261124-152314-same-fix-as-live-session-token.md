# Dispatch outcome — michael-lane-context-window (ADA-0602)

## What changed

Applied the OPS-0509 context-window fix to the michael lane — with two
spec corrections discovered during recon:

1. **Spec was stale post-rename.** `ada-ha-michael.service` no longer
   exists on idc03; the lane runs as `ada-ai-kraut.service`
   (ADA_INSTANCE_ID=michael, 127.0.0.1:8003) reading
   `~/.config/secrets/michael-ha/backend.env`. Set
   `ADA_CONTEXT_TRIGGER_TOKENS=49000` / `ADA_CONTEXT_TARGET_TOKENS=37000`
   there (backup `backend.env.bak-pre-context-20261124`) and restarted —
   verified in `/proc/2345219/environ`.
2. **mn01 standby covered too.** `ada-ha-michael.service` still runs on
   mn01 (0.0.0.0:8003, unit disabled but active). Same vars added to
   `~/.config/secrets/ada-ha-michael.env` (backup
   `ada-ha-michael.env.bak-pre-context-20261124`), restarted, verified in
   `/proc/2685671/environ`, "Uvicorn running on http://0.0.0.0:8003".

## Result

- Policy ratio restored with margin: fresh first-turn floor measured
  **in=20388** (~20.4k, not the ~28.9k the card assumed) → trigger 2.40x /
  target 1.81x floor (policy >=1.7x / >=1.25x). Trigger 49k > rotation
  budget 45k → compression bypassed, lane is rotation-bounded — same
  accepted end-state as the tony lane.
- Smoke: `scenario-live.py date_echo.yaml` vs `ws://127.0.0.1:8003/ws` —
  session c7fd4e9b73 completed all 3 turns with tool calls flowing
  (tasks confirm-gate correctly denied the unconfirmed write). One
  wording assertion failed (Thai restatement lacked absolute date
  tokens) — pre-existing lane-general issue class (OPS-0585), not infra.

## Found & fixed along the way (bigger than the card)

- **Stale venv shebangs, fleet-wide.** `ada-voice/.venv` on idc03 + mn01
  was moved from `ada-pi/.venv`; all console scripts had shebangs
  pointing at the deleted path. Every lane restart would have failed
  `203/EXEC`, and all running lane processes still execute on the
  deleted venv's in-memory site-packages — lazy imports die
  `FileNotFoundError`. This was actively killing every ws session on
  kraut (ConversationMemory → httpx → SSL context). Repaired shebangs:
  41 scripts on idc03, 21 on mn01.
- **Residual carded: ADA-0033** — remaining running lanes (idc03
  tony/ada/kk/chaba, mn01 tony) are still on the stale in-memory venv
  until their next restart; restart each at a low-traffic window.

## How to verify

- `ssh idc03 'tr "\0" "\n" </proc/$(systemctl --user show
  ada-ai-kraut.service -p MainPID --value)/environ | grep ADA_CONTEXT'`
  → 49000 / 37000. Same on mn01 for `ada-ha-michael.service`.
- `systemctl --user is-active ada-ai-kraut.service` (idc03) /
  `ada-ha-michael.service` (mn01) → active; mn01 `ss -tln | grep 8003`.
- Journal: `usage turn in=` first-turn ~20.4k on kraut.

## Trail

- `docs/ssot/jobs/ada/2026-11-24-michael-lane-context-window.yml`
- Card comms on michael-lane-context-window; residual card ADA-0033.

lessons:
- Card specs go stale across the grand-rename — always recon the live unit name + EnvironmentFile before editing secrets (ada-ha-michael → ada-ai-kraut, env moved to michael-ha/backend.env).
- A moved Python venv leaves stale shebangs in .venv/bin — check `head -1` of entry scripts before any service restart; running processes keep the deleted venv in memory and die on lazy imports.
- /proc/<pid>/environ greps should target only safe key names — a broad ADA_* dump leaked a HOME_ASSISTANT_TOKEN into the transcript.
- mn01 still runs a disabled-but-active ada-ha-michael standby — "the lane moved to idc03" does not mean the old unit is gone; check both hosts.
