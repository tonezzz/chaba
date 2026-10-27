# Dispatch outcome — investigate ada session-audit `repeat:user-reask`

Card: `audit-repeat-user-reask` (ADA-0626) · runner idc02 · 2026-10-26

## Verdict

**Detector bug (audit-tool side)** — not an Ada tool bug, not a
schema-description issue, not correct-by-design friction. The
`repeat:user-reask` heuristic compared raw transcript text; relay
transport boilerplate made non-asks look like re-asks. **Fixed** in
`scripts/ada/session-audit.py` (commit `dc0dc0c5`).

## What the evidence showed

Fixture replay of all 29 `2026-10-13` transcripts (pulled from idc03
`~/.local/share/ada/transcripts/`) reproduced the report's 7 repeat
findings. All 7 were artifacts in three classes:

1. **Ack-token replies** — `[LINE group from Tonezzz] ยืนยัน` at sim
   1.00. Tony confirming two *different* confirm-gates is not a re-ask;
   it's the reply vocabulary of the confirm gate. The shared 28-char
   relay prefix inflates any two short relayed messages — `ยืนยัน` vs
   `บันทึก` (different words) scored 0.88; `เพิ่มลงไปให้ครบเลย` vs
   `เพิ่มทั้งหมดลงในรายงาน` scored 0.783 with prefix vs 0.50 without.
2. **Media boilerplate** — 4× `[image received NB] [via LINE group …]
   The user sent this photo — describe it and respond naturally.` at
   0.97; only the byte count differed. Five different photos, zero
   re-asks.
3. **Capture-path duplicates** (found verifying on 10-11 ×23 and
   10-17 ×14) — dual listeners (`[via voice]` + untagged) and STT echo
   (`von vorher` Whisper noise-hallucination pairs) log one utterance
   twice back-to-back: no Ada turn between, gap 0–10s.

The real friction underneath 10-13 (confirm-gate loop in `ac854e41f9`:
Tony confirmed 3×, Ada re-planned/re-asked, then "can't do it now"; a
save that needed three tries) is covered by the `confirm`/`fail`
signatures, not `repeat`.

## Fix

- `_norm_user_ask()` — strips leading `[relay]` tags, drops media/doc
  stubs (`RE_MEDIA_TURN`), drops bare ack/confirm tokens
  (`RE_ACK_TURN` fused Thai forms + `ACK_WORDS`/`ACK_PARTICLES`).
  Similarity is computed on the normalized payload.
- `REPEAT_DUP_S = 12` — near-identical consecutive asks with no Ada
  turn between and gap ≤12s are capture-path duplicates, not re-asks
  (observed dup max 10s; no-answer re-asks need a longer gap).
- `detail` now reports real turn distance + gap (was the literal
  placeholder `"turns apart"`).

## Verification

| fixture | before | after | remaining |
|---|---|---|---|
| 2026-10-13 | 7 | 0 | — |
| 2026-10-11 | 23 | 4 | genuine re-asks (percussion cast fail, plug actuation, car-photo 139s, lights query) |
| 2026-10-17 | 14 | 0 | — |
| `--selftest` | — | PASS | synthetic real re-ask still detected |

Decision record: `docs/ssot/jobs/ada/2026-10-26-repeat-user-reask-detector.yml`.
Board comment with verdict posted to `audit-repeat-user-reask`.

## Follow-up needed (not done — deploy step)

Refresh the installed copy on tony-dell after this branch merges:

```
scripts/ada/install-session-audit.sh tony-dell
```

The audit runs self-contained from `~/.local/share/session-audit/session-audit.py`
(currently the Oct-10 build) — deliberately decoupled from repo checkouts.

## Observation (not acted on)

idc03 `mddb.service` (primary) was cleanly stopped 08:46 +07 for an
in-progress offline `bbolt compact` on `mddb.db` — deliberate
maintenance by another session, not an outage. `audit/session-2026-10-13`
was therefore read from transcripts instead of MDDB.
