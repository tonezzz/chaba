# Dispatch outcome — ada-text-model-promotion-path (attempt 2/2)

## What was done

Card `ada-text-model-promotion-path` is the procedure card for the
ADA_TEXT_MODEL promotion gate: a challenger lane may only take Ada's
text-mode model (or side-tools) after clearing the education-manager
bench gate (`scripts/bench-edu-manage.py`, 13-task fixture, mock WP
store). Attempt 1 died exit=1 after ~3.5 min — provider rate-limit
signature, an infra crash, not a work failure.

This run:

1. Probed live upstreams before benching. OpenRouter `:free` daily cap
   was exhausted (`X-RateLimit-Remaining: 0`, resets ~2026-11-24
   00:00Z / 07:00 ICT) and the Cloudflare neuron tier answered 429 —
   so the card's best-known free challenger (`or-free-nemotron-35`)
   was unrunnable.
2. Pivoted to an unbenched fleet model reachable without those
   upstreams: `qwen2.5:7b` on tony-omen ollama via `--clawbot-ollama`
   (the production `chat-local` leg-1 model; tool-calling verified
   live first — gemma3/phi3 have no ollama tool support).
3. Ran the full fixture: `current` lane (gemini-3.5-flash-lite via
   LiteLLM gateway `/v1beta`, `LITELLM_KEY_CHABA`) + `clawbot` lane,
   judge = gemini-3.5-flash-lite. ~55 min wall (CPU inference).
4. Wrote the durable evidence path:
   `docs/ssot/jobs/models/2026-11-23-ada-text-model-promotion-gate.yml`
   — gate definition, full challenger ledger (12 rows incl. sources),
   the 2026-11-20 evidence gap (those numbers exist only as card comms,
   no committed artifacts), exact re-run procedure, promotion path.

## Result

| lane | F1 | dedupe | ops | recall | draft-Q | completed | p50 |
|---|---|---|---|---|---|---|---|
| current (flash-lite, same-day re-run) | 1.0 | 3/5 | 5/5 | 3/3 | 5.00 (n=5) | 13/13 | 0s |
| clawbot qwen2.5:7b (omen ollama, CPU) | 0.75 | 3/5 | 2/5 | 1/3 | 4.27 (n=3) | 10/13 | 61.7s |

**qwen2.5:7b FAILS every gate axis** — not a promotion candidate; the
chat-local 7B leg stays a chat lane. Incumbent unchanged and stays.
Notable ledger finding: `deepseek-v3.2` (OpenRouter paid, 2026-11-12)
is the only challenger that cleared ALL operational axes (dedupe 5/5,
p50 11.1s) but draft-Q 4.67 < 5.0 — the original AQ remains uncleared
by anything free or paid.

## Deliverables (committed on dispatch branch, not pushed)

- `reports/bench-edu-manage-2026-11-24-qwen25-7b-omen-gate.{json,md}`
  (force-added — `reports/*` is gitignored; prior bench reports were
  force-added the same way)
- `docs/ssot/jobs/models/2026-11-23-ada-text-model-promotion-gate.yml`

## How to verify

- `python3 -c "import yaml; yaml.safe_load(open('docs/ssot/jobs/models/2026-11-23-ada-text-model-promotion-gate.yml'))"`
- Read the scorecard table in the `.md` report; JSON has per-task
  detail + fidelity counters.
- Card comms have the same summary (posted as `devin`).

## Follow-ups (not done — out of scope/gated)

- Re-run `or-free-nemotron-35` + paid gemini pair after the OR free
  reset (~07:00 ICT) to commit the missing 2026-11-20 artifacts —
  procedure is in the job yml `rerun_procedure:`.
- Promotion itself needs Tony's explicit approval and an ada-voice
  side change — correctly not attempted.

lessons:
- reports/* is gitignored — bench report artifacts need `git add -f` or the session-end auto-commit will silently skip them.
- LiteLLM per-key model allowlists differ: LITELLM_KEY_BENCH is alias-restricted (403 on bare gemini-3.5-flash-lite); LITELLM_KEY_CHABA/ADA can call it on /v1beta — check `/v1/models` per key before assuming access.
- bench-edu-manage.py needs `/home/tony/reports/skills/{filing,ops,recall}.md` (host-local, never committed) for agent-lane skill text — absent on tony-macbook, so agent scores there are a lower bound.
- tony-omen ollama serves qwen2.5:7b CPU-only (api/ps size_vram=0): agent-loop bench tasks run 15-580s each — budget ~1h for a 13-task clawbot rep; gemma3/phi3 lack tool support in ollama.
- OR :free daily cap is account-level on the gateway's OPENROUTER_API_KEY — all or-free-* aliases die together until reset; probe with one cheap call before committing to a bench run.
