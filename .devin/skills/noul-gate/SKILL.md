---
description: Noul-gate — ask the Jev /v1/systemone decision layer whether a planned destructive/risky op is safe to run unattended, before running it
---

# Noul-gate — advisory safety gate for destructive ops

Use before any operation that could be irreversible, destructive,
spend money, or impact production — the same class AGENTS.md lists as
real gates. The gate adds a second opinion; it never replaces the
standing rules.

## When to use

- Before `rm -rf`, `git reset --hard`, `DROP`/`DELETE` on shared
  state, service stops/restarts on production hosts, credential or
  config changes, deploys, pushes, or anything the AGENTS.md
  "real gates" list covers.
- NOT needed for routine read-only/local/reversible work — the call
  costs ~70s on the default backend.

## How

```bash
python3 scripts/jev/noul-gate.py "<the exact command or operation>" \
    [--context "host, reversibility, prior approval"] [--json]
```

Exit codes: `0` clear · `3` gate (p_safe < threshold — stop and get
explicit human approval) · `2` endpoint error (fail-open, warn).

Default backend: open-jev heavy `gemma-3-4b-it` at
`http://100.75.102.88:8777` (~70s/call, discriminates correctly —
measured 2026-11-24). Override with `--url` or `JEV_NOUL_URL`.

## Backend reality (measured 2026-11-24, card KNB-0822)

| backend | noul on destructive-op phrasing | verdict |
|---|---|---|
| jev-student-distilmulti omen:8780 | collapses ~0.006 — says CLEAR on `rm -rf` prod | DO NOT USE for gating (domain-locked to Ada confirm-gate) |
| openjev student-1b omen:8778/8779 | orders roughly but compresses (rm -rf p=0.50); ~12s | cheap pre-filter only, never gate of record |
| openjev heavy-4b omen:8777 | rm -rf prod 0.003 vs routine ops 0.98-0.99; ~70s | default gate of record |

Question polarity matters: ask "is it SAFE to run unattended?"
(p_safe >= 0.5 → clear). The approval-phrased variant made the 1b
gate everything (git status p=0.75).

## Rules

1. A `gate` verdict = stop, surface the op + p to the operator, wait
   for explicit approval. A `clear` verdict does NOT authorize
   anything the standing rules already gate.
2. Endpoint down/bad answer → fail-open with a printed warning; do
   not retry-loop, and do not treat unavailability as clearance.
3. Record the verdict (`--json` output) in card comms or the session
   summary when the op was gated — the p is the audit trail.
4. Threshold is `--threshold` (default 0.5); raise it toward 0.8 for
   extra caution on prod hosts, lower never below ~0.3.
