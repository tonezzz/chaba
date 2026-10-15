# Dispatch outcome — correction commands die at the confirm gate

Card: `correction-commands-die-at-the-confirm-g-05902a` (OPS-0567)
Runner: tony-macbook · Base: ada-voice `main` @ `41020cf`

## What was wrong

Transcript `2026-10-13-cac2984711`: Tony said "CRV เป็นรถของกุ้ง
ไม่ใช่ของผมนะ แก้ไขด้วย" — an explicit fix order. Kaewta acknowledged but
asked permission to write it; the session ended and the correction never
landed. Two layers caused it:

1. **Instruction** — `DEFAULT_ADA_INSTRUCTIONS` covered explicit
   "remember that" asks as self-confirming but said nothing about
   *correction* orders, so the model defaulted to confirm-first.
2. **Gate** — even a compliant `confirmed=true` call would have been
   stripped by the provider: `แก้ไขด้วย` is not in the affirmation
   regex, so the bank `write_policy=confirmed` gate would deny and force
   a propose→deny→retry round-trip that the session never survived.

## What changed (staged drop 11 in `integrations/ada-voice/`)

- `backend/realtime_provider.correction-command.patch` —
  `realtime_provider.py`:
  - `_MEMORY_DIRECTIVE_RE` — explicit store/correct/retract orders, Thai
    + English (จำไว้/จดไว้/บันทึก/เก็บไว้/แก้ไข/เปลี่ยนเป็น/อัปเดต/
    ลืม…/ลบ…/เอาออก; remember/note/jot/write down/record/save/fix/
    correct/change/update/forget).
  - `_user_memory_directive()` — vetoes: trailing-question guard,
    negation in the 40-char lead (`อย่าจำ`, `don't record that`,
    `ไม่ต้องแก้` — bare ไม่ deliberately excluded so 'ไม่ใช่ของผมนะ
    แก้ไขด้วย' still authorizes), and the 'I/you remember X'
    recollection exclusion.
  - `_memory_directed_call()` — scopes authorization to the memory-write
    seats only: `ada_remember` bank kinds, `ada_forget`,
    `ada_ops action='outcome'`. Actuation/capture/CMS/calendar/devin
    calls can never be directed.
  - Dispatch: a directed call counts as affirmed; `confirmed=true` +
    `_verified_affirm` are injected so even a bare `ada_remember` lands
    in ONE call; a `memory_directive_authorize` ops event records it.
  - Instructions: explicit remember/correct/forget orders are the
    authorization — write in the SAME turn (key=/supersedes= when known),
    report in one clause, never re-ask; confirm-first stays for
    inferred/uncertain facts.
- `backend/tool_guide.correction-command.patch` — ada_remember/ada_forget
  guide text: an explicit order IS the yes.
- `tests/test_memory_directive.py` — NEW unit tests (detector positives/
  negatives + seat scoping).
- Chaba side: `tests/ada/test_correction_command.py` — patch-apply gate +
  patched-tree unit run (skips where no ada-voice venv).
- `docs/ssot/apps/ssot.apps.ada-memory-banks.yml` — write_policy text now
  documents directive-authorization.

## Result / status

Staged, not deployed — ada-voice edits land on tony-dell per the deploy
policy and need explicit approval. Install steps are in
`integrations/ada-voice/README.md` (Drop 11): `git apply` both patches on
`main` @ `41020cf`, copy the test file, run the deploy gates.

## Verification done here

- `git apply --check` clean on a fresh clone @ `41020cf`; `py_compile` clean.
- Detector verified against the patched tree's real code (extracted via
  ast, dependency-free): the exact incident turn authorizes; 22 positive +
  19 negative utterances all correct; non-memory tools never directed.
- `_user_confirmed` and the runner-side gate are untouched — all existing
  confirm tests (`save that note` ≠ consent, negation/question vetoes,
  token replay) still hold.
- Secondary-speaker block, content scan, bank ACL, and pending-lane
  staging are all upstream/unchanged — the directive only spends the
  voice-confirmation round-trip the user already paid.

## Known residual

- Directed authorization is memory-writes only. Extending the same
  self-authorization to calendar/CMS writes is a separate decision.
- A directive authorizes the write the model chose to make — it can't
  fix a wrong tool choice (e.g. 'fix the TV' → memory write still lands
  unconfirmed-but-writable). Reversible via ada_forget; recurrence would
  warrant a target check, not a gate change.
