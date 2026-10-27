# Dispatch outcome — gemini-imagegen-dedicated-key (2026-10-27)

## Verdict: task is superseded — no key minted, no code changed

The card's premise is dead on two independent counts, both verified
against SSOT and the live gateway config in this worktree:

1. **The free-tier image model no longer exists.** `gemini-2.5-flash-image`
   was retired upstream by Google on 2026-10-11 — the same day the 429
   that motivated this card was observed. Its replacement
   (`gemini-3.1-flash-image`) is **paid-only upstream — no free tier**
   (`docs/ssot/infrastructure/ssot.llm-gateway.yml`, image class note).
   A freshly minted free AI Studio key would have zero quota on any
   image model — dead on arrival.

2. **The quota-contention problem was already solved differently.**
   Card `ada-render-image-v2` (ADA-0643, done + deployed + live-verified
   2026-10-14) rebuilt `ada_render_image` on the LiteLLM gateway `image`
   class: `gemini-3.1-flash-image@paid -> gemini-3.1-flash-lite-image@paid
   -> or-gemini-3.1-flash-image`
   (`stacks/idc03/litellm/config.yaml`). Per-lane virtual keys meter the
   spend (LITELLM_KEY_KK → ada-kk, $5/30d caps); voice/chat run on
   separate per-lane paid keys (GEMINI_API_KEY_KK etc., landed
   2026-10-13). Shared free-key contention cannot recur.

The card itself already carried a SUPERSEDED comm (2026-10-14)
recommending closure — this dispatch confirmed that recommendation
against the deployed state. Grep: `ADA_IMAGE_GEN_KEY` appears nowhere in
the codebase except the card spec.

## Changed

- `docs/ssot/jobs/ada/2026-10-27-imagegen-dedicated-key-superseded.yml`
  — decision record (do-not-mint; revisit only if a free image model
  returns).
- This outcome file.

## Board

- Posted findings comment on `gemini-imagegen-dedicated-key`.
- Attempted close via board-api `/action do:close` — blocked by the
  dispatch merge guard while this branch is unmerged; the card should
  be closed after merge (or on sight — evidence is on the card).

## Verify

- `grep -n "image" stacks/idc03/litellm/config.yaml` — image alias +
  paid chain.
- `grep -n "image:" docs/ssot/infrastructure/ssot.llm-gateway.yml` —
  class chain + paid-only note.
- `cat docs/ssot/kanban/cards/ada-render-image-v2.yml` — done,
  deployed, live-verified.
