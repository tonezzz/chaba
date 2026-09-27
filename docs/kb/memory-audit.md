# Memory audit — KK misses, confident-gate incident, scenario assessment

Date: 2026-09-27 · incidents from live sessions + scenario runs

## Why Ada misses KK's memory — root cause chain

1. **Extraction lands in Tony's bank.** `speaker_identity` routes
   extracts to `personal-kk` only when speaker-ID resolves KK. Since
   2026-09-24 her sessions resolve to admin/Tony (mis-identified or
   unidentified → caller identity) → extracts land in
   `ada-ha-bank-personal-tony` (daily) while `personal-kk` froze at
   9-24. Then ACL (`person.kk` allow-list) blocks her from reading where
   her own data went.
2. **Wiped docs poisoned ranking** (fixed today `6745f31`): 3 of 10
   personal-kk docs had contentMd='' yet scored ~0.6 — they crowded the
   real hits out. Now: empty hits skipped, meta-only writes refuse when
   the read fails, dead docs retracted.
3. **Profile contamination** (`Timmy`, `NewSpeaker`) still muddies
   speaker-ID → feeds issue 1. Awaiting approval to remove + re-enroll.

Evidence: KK=กุ้ง=Sok Hiang merge note + "CR-V ขาว 5ขว 6249" +
Underworld/EDM + แก้วตา assistant-name all found inside
`ada-ha-bank-personal-tony` extracts 2026-09-26.

## The confident-gate incident — explained

Ada refused "dig deeper" (`recall_gate_override` reproduces it):
server-side `_recall_gated` refuses `ada_session_recall` for 60s after a
confident memory_search hit (score≥0.6). Rationale is sound — saves the
~20s NotebookLM round-trip — but the gate trusted hits whose bodies
were empty, and gave the user no override path.

**Balance now in place** (`d96cf88`):
- Gate only counts confident *content-bearing* hits (empty hits gone)
- `force=true` escapes the gate on explicit push ("dig deeper", "check
  again", "you missed it") — verified live: turn 2 reached recall
- Instruction names the override so she doesn't second-guess it

## References lifecycle — tested (`report_references_lifecycle`, PASS)

Create-with-references → publish → "remove references" → update →
re-read. Workflow valid; found and fixed a real regex bug along the way:
`confirmed?` never matched bare "confirm" (`10f0211`).

## Scenario structure — assessment

**Pros**
- Declarative YAML, one file per capability — easy to add
- `calls_any`/`no_calls_except`/`response_nonempty`/`reconnect` cover
  the real axes; `cleanup.mddb_delete` keeps banks clean
- Live traces caught 4 real bugs today (regex, sticky identity, dead
  stream, wiped docs)

**Cons**
- English expectations vs Thai answers — can't assert on response
  content (`response_contains` only works same-language)
- No speaker-ID injection — can't simulate "talking as KK" so
  per-person memory routing is untestable end-to-end
- `calls_any` silently passes if the runner's tool-name list drifts
  from reality (add a `known_tools` check against the declaration set)
- No per-turn assertions on *args* (e.g. `provider=duckduckgo` asserted
  only via journal grep, not the scenario)

**Suggested improvements**
- `response_regex` + `response_lang` assertions (transcript is captured
  already)
- `speaker:` per-session field → `?speaker_override=person.kk` query
  param honored by the session path, so KK-scoped flows are testable
- A `--dry-run known_tools` lint: every `calls_any` name must exist in
  the declared tool set
- Coverage matrix job (running on mn01) → auto-flag uncovered tools
