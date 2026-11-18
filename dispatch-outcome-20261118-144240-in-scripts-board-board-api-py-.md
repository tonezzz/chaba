# Dispatch outcome — board-api-compact-cards (2026-11-18 14:42)

## Finding: card premise was stale

`/cards?fields=a,b,c` was **not** ignored — the AUD-1033 projection already
works on live idc03. Verified before changing anything:

| request (live idc03) | size | time |
|---|---|---|
| `GET /cards` (bare) | 9.67 MB | 16.1 s |
| `GET /cards?fields=id,ref,title` | 123 KB | 0.42 s |
| `GET /cards?compact=1` | 209 KB | 0.76 s |
| `GET /cards?compact=2` (before fix) | **9.67 MB** | 15.6 s |

The earlier 8.8MB/13s test was payload-bound, exactly as the spec suspected.
The one real bug: `compact=2` was a silent fall-through — `_truthy("2")` is
false → empty field set → the *heaviest* possible response (full dump) for a
caller asking for the lightest. Comms are the bulk: ~8.3 MB of the 9.66 MB.

## What changed (`scripts/board/board-api.py`, +93/−7)

- **`compact=2` tier** — `COMPACT2_FIELDS` = {id, ref, title, column,
  priority, updated, brief, spec, action_status}. `action_status` kept
  synthesized per OPS-1107 (a projection without it made consumers see
  "no queued cards"). Any enabled `compact` value other than `2` maps to
  tier 1 — no value can silently fall through to a full dump again.
  `compact=0/false/no/off` still disables.
- **`comms_tail=<n>`** — keeps only the last n comms entries per card and
  stamps `comms_total`; `comms_tail=0` drops comms entirely (≈ the 1MB
  comms-excluded read from the card). Works on `/cards` (alone or combined
  with `fields=`/`compact=`) and on `/card/<id>`. Trims into a copy —
  the load_cards read cache is never mutated (verified: an untailed
  re-read still returns all comms).
- **Docstring** — new params documented in the endpoint header.
- **Selftest** — added a `card_query` block covering fields/compact=1/2,
  comms_tail=0/1/2, `fields=comms&comms_tail` combination, cache
  non-mutation, garbage-value tolerance, `compact=0` disable, and the
  `compact=9` → tier-1 mapping. `python3 scripts/board/board-api.py
  --selftest` → `selftest ok`.

## Verification (local instance, real 931-card dataset, this worktree)

| request | size | time |
|---|---|---|
| `/cards` bare (unchanged) | 9.66 MB | 2.17 s |
| `/cards?fields=id,ref,title` | 123 KB | 27 ms |
| `/cards?compact=1` | 208 KB | 27 ms |
| `/cards?compact=2` | 789 KB | 38 ms |
| `/cards?comms_tail=5` | 2.55 MB | 72 ms |
| `/cards?comms_tail=0` | 1.39 MB | 46 ms |

Shapes checked: `compact=2` returns brief+spec+action_status, no
comms/action; `comms_tail=2` on the live card returns last-2 comms +
`comms_total: 22`; `/card/<id>` honors both params. Backward compat: bare
`/cards` still returns the raw payload (no envelope).

Post-merge, live idc03 `/cards?compact=2` should drop 9.67MB/15.6s →
~0.8MB/<1s. ada-voice `_board_cards`/`_compact_cards` can then drop their
client-side workarounds — `comms_tail=0` or `compact=1` for list views,
`compact=2` when brief/spec are needed, `comms_tail=N` for recent chatter.

Not done (per dispatch rails): no commit to master, no push, no deploy —
the served checkout picks this up through the normal merge path.
