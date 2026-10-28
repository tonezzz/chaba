# dispatch outcome — devnest-tg conversational card follow-ups

Card: devnest-tg-conversational-card-followups (KNB-0960)
Runner: idc02 · 2026-10-28

## What changed

`scripts/devnest/devnest-tg-relay.py` — card commands now carry a durable
per-topic conversation context so follow-ups don't need the ref repeated:

- **`card-context.json`** (new, in STATE_DIR): per `<chat>:<thread>` last-card
  context — card id/ref, timestamp, sender, topic, use-count. Expires after
  `DEVNEST_CARD_CONTEXT_TTL` seconds (default 7200); refreshed on every
  successful card reply. Stores card *identity* only — every reply
  re-fetches the board (`_card_index`/`resolve_card`), never cached text.
- **Read-only follow-ups** (anchored whole-message, filler words stripped,
  exact-alias match so ordinary chat never triggers): `easier|simple|eli5`,
  `in thai|ภาษาไทย`, `why`, `evidence|what evidence`, `next|what next`,
  `history`, `spec`. New renderers: plain-terms summary, Thai-labelled
  summary, why (brief+blockers), evidence (verify checks+comms), next,
  history (recent comms), spec.
- **Embedded refs**: `0959 with easy language.`, `explain 0959 in thai`,
  `spec ops-0905` resolve the named card and reset context to it. Bare
  digits inside phrases limited to `0?\d{3}` so "2026" isn't a ref.
- **No/expired/corrupt/wrong-sender context → asks for a ref** (audit
  `result=need_ref`); a different sender's follow-up is treated as
  ambiguous, never guessed. Wrong topic = no context (per-thread keys).
- **Mutations untouched**: APPROVE/REJECT still require an explicit literal
  ref + approver gate; bare `APPROVE` is refused even with live context;
  follow-ups make zero board writes.
- Bare `explain`/`status` now uses the context card; `explain easier`
  reads as the follow-up, not a card named "easier".
- General/topic reply routing and the unauthorized/quarantine capture
  paths are unchanged; context keys include the thread so topics isolate.

`tests/test_devnest_tg_relay.py` — +15 tests: phrase parsing, context
write, context follow-up, fresh-board fetch per reply, no-context ask,
expiry, wrong sender, wrong topic, explicit-ref override, unknown ref,
Thai/simple rendering, bare explain, evidence/history/spec replies,
APPROVE still explicit, audit entries.

`docs/ssot/jobs/devnest/2026-10-28-tg-card-conversational-followups.yml` —
trail doc.

## Result

- `pytest tests/test_devnest_tg_relay.py`: **55 passed** (40 existing +
  15 new), pytest 9.2.0 in a scratch venv (host has no pytest installed).
- **Live verification vs real OPS-0959** (`opencode-explicit-executor-routing`)
  through board-api `idc03.taila0626a.ts.net:10000` with Telegram send
  stubbed: `explain OPS-0959` → English summary; `easier.` → plain terms;
  `in Thai` → Thai-labelled summary; `what evidence?` → evidence;
  `what next?` → next; `0959 with easy language.` → simple w/ explicit
  ref; `spec`/`history`/`why` all resolve. Audit records
  `followup_ok`/`need_ref` with kind, ref_source, context_ref,
  context_age_s; context file shows uses counting.

Tony's exact refused messages from the live audit — `easier.`,
`in Thai`, `0959 with easy language.` — all now answer correctly.

## How to verify

```
python3 -m pytest tests/test_devnest_tg_relay.py -q     # 55 passed
```

Live: in the DevNestHA group, `explain OPS-0959` then `easier`,
`in Thai`, `what evidence?`, `what next?` — replies resolve the same
card without repeating the ref; check STATE_DIR/audit.jsonl for
`followup_ok` entries and card-context.json for the binding.

Not done (out of scope): no push, no deploy — the running relay keeps
old behavior until the updated script is deployed by its owning unit.
