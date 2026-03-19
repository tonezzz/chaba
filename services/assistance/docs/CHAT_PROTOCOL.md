# Chat Protocol (Operator ↔ Assistant)

This repo uses a simple chat-driven operating loop.

## Source of truth

- `services/assistance/docs/ACTION.md` is the authoritative operator playbook.
- `services/assistance/docs/TODO.md#now` is the authoritative queue.
- **Rule:** `ACTION.md` “Now” must always reference the top item in `TODO.md#now` by ID.

## Commands (what to say)

### `next?`
- Meaning: “Tell me what to type next.”
- Expected assistant response:
  - Identify the top queue item in `TODO.md#now`.
  - Tell you the exact next utterance to make (usually `action`).

### `action`
- Meaning: “Execute the current `Now` item.”
- Expected assistant behavior:
  - Execute exactly one Smallest Next Action (SNA): the top item in `TODO.md#now`.
  - Use the success criteria in `ACTION.md` for pass/fail observables.
  - Capture minimal evidence (endpoint responses / key fields).
  - Rotate the queue:
    - mark the completed TODO item `[x]`
    - promote the next item into `TODO.md#now`
    - update `ACTION.md` “Now” pointer to match

### `proceed.`
- Meaning: “Continue the current SNA / complete the next step in the same procedure.”
- Use when you already agreed on a specific plan and just want it executed.

### `redeployed.`
- Meaning: “The deployed service was redeployed; re-run verification.”
- Expected assistant behavior:
  - Re-run only the verification steps needed to confirm the fix is live.
  - If verification passes, rotate back to the next queue item.

### `stop`
- Meaning: “Do not run tools; summarize and wait.”

## Guardrails

- **WIP limit = 1**: only one in-progress SNA at a time.
- **No side quests** during an SNA: if something unexpected comes up, replace “Now” with a single highest-leverage inspection step.
- **Always leave the system in a safe state**:
  - watchers stopped when possible
  - doc queue consistent (`TODO.md` and `ACTION.md` agree)

## Evidence format (keep it short)

When reporting results of an `action` run:

- 1-2 lines: pass/fail and what was executed
- 2-5 bullets: key observables (HTTP status + 2-3 fields)
- 1 line: what to say next
