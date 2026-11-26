# dispatch outcome — doc-draft-verifier-semantic-gap (OPS-1014 evidence)

## What the card asked

OPS-1014 evidence: qwen2.5:32b emitted a code-summary of runner-agent.py
instead of the specced model-notes doc, yet the doc-draft verifier passed.
Options on the card: spec-author sentinel discipline, a spec-vs-doc
keyword-coverage check, or accept the mechanical gate + mandatory human
review. Recommendation (taken): keep the mechanical gate, document that
doc-draft cards need specific sentinels, add optional
`verify_regex`/`verify_min_terms`.

## What I found (deeper than the card's framing)

The archived OPS-1014 card (`devnest-fl-pilot-modelnotes`) declared **no**
verify contract at all — and *could not have*: `verify_contains` /
`verify_sections` were never in board-api's `ACTION_KEYS`, so `/card`
silently dropped them. The sentinel path in verify.py was unreachable via
the write door; only structural checks (size, markdown shape, no
placeholder markers) ran, and a code summary passes all of them. Verified
against git history: the merged artifact at `9a9323775e` is the
code-summary; `c5d6978a49` later hand-corrected the KB page.

## What changed

- `evals/opencode-lane/profiles/{doc-draft,artifact-write}/fixture/verify.py`
  — `_card_sentinels` → `_card_contract` fetching all four
  `action.verify_*` keys live from board-api (fail closed on fetch error).
  New optional checks: `verify_regex` (all patterns must match;
  uncompilable pattern fails closed) and `verify_min_terms`
  (`{terms, at_least}` case-insensitive coverage; bare list = all
  required; vacuous/unsatisfiable spec fails closed). Sentinel semantics
  unchanged.
- `scripts/board/board-api.py` — `ACTION_KEYS` gains all four `verify_*`
  keys; `do_create` validates shapes (string-or-≤20-strings for
  sentinels/regex, regexes must `re.compile` at the door,
  `verify_min_terms` = `{terms: ≤50 strings, at_least: int∈[1,len]}` or
  bare term list). Covers create + re-queue paths.
- Docs: `task.yaml` contracts (both profiles), doc-draft `prompt.md`,
  `profile.yml` description, `PROCEDURE.md` (new "Card-declared verify
  contract" paragraph — incl. the held-out note: verify_* values are
  NOT injected into the agent prompt, spec prose still carries the
  instruction), `docs/kb/opencode-lane-model-notes.md` weakness section
  rewritten as resolved, `docs/kb/board-api-write-door.md` endpoint note.
- Tests: `tests/devnest/test_doc_draft_verify.py` (new, 10 tests incl. an
  OPS-1014 replay: code-summary passes with no contract, fails once a
  realistic contract is declared, correct doc passes the same contract);
  `tests/board/test_executor_contract.py` (+2 tests: verify_* persist
  through `do_create`, bad shapes rejected).
- Trail: `docs/ssot/jobs/devnest/2026-11-24-doc-draft-verifier-semantic-gap.yml`.

## Result / verification

- `python3 -m pytest tests/devnest/test_doc_draft_verify.py -q` → 10 passed.
- `python3 -m pytest tests/board/test_executor_contract.py -q` →
  116 passed, 17 subtests.
- `python3 scripts/devnest/opencode_profiles.py lint` → no errors.
- All touched YAML parses.

Semantic doc quality is still NOT mechanically gated — per the card's own
recommendation, human doc review at closeout remains required; the new
fields only raise the floor.

lessons:
- verify_contains/verify_sections were read by the fixture verifiers but absent from board-api ACTION_KEYS — declared contracts were silently dropped at the write door. When a verifier reads a card field, check ACTION_KEYS first.
- The OPS-1014 "sentinel match" story was imprecise: the card declared zero sentinels; only structural checks ran. Check the archived card's action block before trusting the evidence framing.
- verify_* contract is held-out by design — values must NOT be injected into the agent prompt; spec prose carries the instruction, verify_* enforces it.
