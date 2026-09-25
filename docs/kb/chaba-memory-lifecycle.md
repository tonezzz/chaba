# Chaba memory lifecycle — as-built vs needed

Review doc, 2026-09-25. Traces one memory item end-to-end:
conversation → capture → focus selection → control file → render/inject → fade-out.

## The pipeline as it exists today

```
CONVERSATION                         CAPTURE                    FOCUS / ROLLUP
─────────────                        ───────                    ──────────────
Ada voice (idc01)                    transcripts/*.md ──┐       export-transcripts.py
  conversation_memory ──────────────► reports/*.json ───┤        (30-min pull timer)
  (L1 LLM report per session end)    session-memory.md ─┤          │ session-report.py
                                     events.md (new) ───┤          │ focus-rollup.py
Chaba guest chat (tony-dell)         chaba/session-      │          │  └─ focus-index.json
  _mark_session_end ────────────────► memory.md          │          │     + focus-digest.md
                                     events.md           │          │ journal-report.py
                                     users/guests/*.yml ─┤          │  └─ session-ops.jsonl
Devin sessions (this host)           immediate.yml ──────┤          │ host-report.py
  SessionEnd hook ──────────────────► recent-events.yml ─┤          │  └─ host-ops.jsonl
                                     devin session-      │          ▼
                                     memory.md           │    ~/.local/share/ada-review/
                                                        │    ~/.local/share/chaba/
                                                        │
CONTROL FILE                          RENDER             INJECT
────────────                          ──────             ──────
docs/ssot/chaba/                      render-memory.py    context.md → devin session start
  ssot.chaba.memory.yml                 (deterministic,   context-guest.md → guest WS prime
  sections/priorities/limits/           no AI)              (per-connect via CHABA_RENDER_CMD)
  overflow_order                                             report.yml → on-demand deep query

FADE-OUT
────────
rolling-log max_entries · recent-events ttl_hours (72h) · overflow_order drops
· immediate.yml overwrite · events.md 120-cap · ada valid_until + staleness sweeps
```

## Stage-by-stage: have vs need

### 1. Conversation → capture — ✅ solid

| Have | Detail |
|---|---|
| Ada voice | transcripts + per-session L1 reports + rolling session-memory.md |
| Guest chat | transcript tail → `session-memory.md` at session end |
| Devin | `notebook-summaries/session-memory.md`, `immediate.yml` working set |
| Events | `events.md` (first-contact/registration/promotion), `recent-events.yml` hot tier |
| Identity | `first_seen`/`last_seen` on user/guest files; `issued` on keys |

### 2. Capture → focus selection — ⚠️ half-automated

| Have | Gap |
|---|---|
| `focus-rollup.py` groups session reports by emergent tags, `first → last` spans, open loops — works | It only sees **Ada-side** reports; chaba/devin sessions never produce focus entries |
| `recent-events.yml` = hot tier with ttl | **No promotion rule** — nothing moves a hot event into `focus` (manual/agent action only) |
| `ssot.focus.current.active.yml` focus file | Edited by agent intent, not by signal — an item mentioned 5 sessions in a row doesn't auto-surface |

**Need:** two promotion mechanics —
- **ttl refresh**: a re-mentioned event should bump its `ts` instead of appending a near-dup (current behavior: append; the old entry still expires mid-thread → topic flickers out)
- **promote path**: recent-event referenced ≥N times or pinned → moves to focus file (agent-mediated is fine, but there should be a defined trigger)

### 3. Focus → control file — ✅ correct by design

`memory.yml` is the *shape* (sections, priorities, limits, overflow order, sources) —
not content. Changes via git only. That's the right boundary.

### 4. Control file → render/inject — ✅ solid

| Have | Detail |
|---|---|
| Render triggers | Devin SessionEnd (full render), SessionStart `--if-stale`, guest per-connect |
| Bounded | per-section soft/hard limits + `overflow_order` drop sequence |
| On-demand depth | `report.yml` carries the full untruncated data |

### 5. Fade-out — ⚠️ partial

| Have | Gap |
|---|---|
| rolling-log `max_entries` tail-cap | applies at **render**; the source files themselves grow unbounded (`session-memory.md`, `reports/`, transcripts on the mirror) |
| `recent-events` 72h ttl | expires at render — but no ttl refresh on re-mention (stage-2 gap) |
| `overflow_order` | drops whole sections when over hard cap — coarse but safe |
| `immediate.yml` | overwritten per session — self-cleaning |
| focus digest | **no expiry** — a tag persists as long as its reports exist; old topics never fade |
| ada side | `valid_until` + staleness sweeps + scenario-report 14-day retention — complete |

**Need:**
- focus-rollup window/dormancy — collapse or drop tags with `last_seen` > N days
- retention sweep for mirrored `reports/` + `transcripts/` (e.g. 30d) — they accumulate on this host
- file-level caps on chaba-side logs (events.md already 120; session-memory.md uncapped on disk)

## Proposed closing moves (ordered)

1. **recent-event.py: refresh on re-mention** — same `--ref` (or fuzzy same text) updates `ts` in place instead of appending a dup. ~20 lines.
2. **focus-rollup dormancy** — tags with `last_seen` > 14d collapse to a single `## dormant` line (or drop); keeps digest honest about what's actually live. Belongs to that pipeline's owner session — coordinate.
3. **Mirror retention** — `export-transcripts.py` prunes local `reports/*.json` + `transcripts/*.md` older than 30d (remote untouched).
4. **Optional: `where`/`how` event fields** — auto-derived (hostname + callsite), yaml carries them, heading stays lean. Pending your call from the earlier pros/cons.
5. **`session-memory.md` file cap** — same 120-entry trim as events.md on append.

Nothing here changes the trust boundary: all writes stay local-file, render stays deterministic, ada↔chaba separation preserved.
