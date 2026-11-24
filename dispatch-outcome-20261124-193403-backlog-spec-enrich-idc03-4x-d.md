# dispatch-outcome — backlog-spec-enrich-idc03-4x-d (ops-1037 / OPS-1316)

## What changed

`backlog-spec-enrich` (idc03, 4x/day) no longer calls Gemini with a raw
API key. It now rides the LiteLLM gateway through the existing
`scripts/ada/litellm_chat.py` OpenAI-compatible caller.

Commits on `dispatch/20261124-193403-backlog-spec-enrich-idc03-4x-d`:

- `ca6d8ee27ac` feat(ops): route backlog-spec-enrich through LiteLLM gateway
  - `scripts/ops/backlog-spec-enrich.py` — new `ENRICH_PROVIDER`
    (`litellm` default | `gemini`). litellm path calls
    `litellm_chat.chat_json` → `POST {LITELLM_URL}/chat/completions`
    with `x-litellm-tags=service=backlog-spec-enrich,job=backlog-spec-enrich`
    and `x-litellm-metadata={route:spec_draft, card:<id>}` — SpendLogs
    attribution, per-key budget (chaba key), and the model's registered
    fallback chain all apply. `ENRICH_MODEL` is now any gateway
    `model_name` (`gemini-3.5-flash-lite` default;
    `ollama-qwen38b-kkmac`/`chat-local` for free local drafts).
    Fallback: `ENRICH_PROVIDER=gemini` keeps the legacy direct path;
    a failed/empty litellm reply also falls back to `gemini_rest` when
    the model starts with `gemini` and a direct key resolves.
  - `docs/ssot/infrastructure/ssot.jobs.yml` — job gains
    `env_file: litellm-chaba.env` (supplies `LITELLM_KEY` = chaba
    virtual key), `LITELLM_URL=http://100.102.134.91:4000/v1`,
    `ENRICH_PROVIDER=litellm`.
  - `systemd/generated/idc03/backlog-spec-enrich.service` — re-rendered
    (`render-jobs.py --host idc03 --ids backlog-spec-enrich`).
  - `docs/ssot/infrastructure/ssot.llm-gateway.yml` — proof_lanes entry.
  - `tests/ops/test_backlog_spec_enrich.py` — 7 tests covering
    provider routing, attribution kwargs, and fallback gating.
- `23e9891bcfd` chore(jobs): re-render con01 chaba-system-report unit
  - Pre-existing drift: manifest had `kk-mac` in the audit-hosts fan-out
    but the generated unit was stale; `test_render_jobs
    GeneratedTree` failed on clean HEAD and blocked the commit gate.

## Verification

- `pytest tests/ops/test_backlog_spec_enrich.py` — 7/7 pass.
- `pytest tests/ops/test_render_jobs.py` — 27/27 pass (incl. generated
  tree == manifest guard).
- Live smoke from tony-dell with `litellm-chaba.env` creds + fixture
  card, `--dry-run`: real gateway call returned a valid `ask` decision
  for `gemini-3.5-flash-lite` through the chaba key.
- Failure paths verified live: bogus model → gateway 403 → clean skip;
  dead `LITELLM_URL` → litellm no-op → `gemini-*` model triggers
  gemini_rest fallback → "no GEMINI key" on this host (keys live on
  idc03) → card skipped, no crash. `ENRICH_PROVIDER=gemini` without a
  key exits 1 with the legacy message.
- Deploy note: the idc03 unit picks up `EnvironmentFile` +
  `Environment=` on next `render-jobs.py --host idc03 --install` (or
  manual unit copy + daemon-reload) after merge — the repo change
  alone does not restart the timer.

## Notes / leftovers

- `scripts/blocks.json` docstring catalog was stale by dozens of
  entries; regenerating produced unrelated churn, so it was reverted —
  next `blocks-index.py` run picks up the new "via LiteLLM" desc.
- `docs/ssot/ssot.dev-system.assessment.yml` shows an unstaged
  hook-generated refresh in the worktree — left untouched.
- Pre-commit "single-writer" warning: worktree is 33 commits behind
  origin/master; merge will need a rebase (card-yaml union driver
  covers card files; no card files touched here).

lessons:
- `litellm_chat.py` already exists (scripts/ada) — OpenAI /chat/completions + x-litellm attribution; reuse it instead of writing a new gateway client.
- Job secrets pattern: `env_file: '%h/.config/secrets/litellm-chaba.env'` supplies LITELLM_KEY (chaba virtual key); add `LITELLM_URL` + provider envs in the ssot.jobs.yml `env:` block, then re-render with `render-jobs.py --host <h> --ids <job>` (never --install from a satellite).
- `test_render_jobs.py::GeneratedTree` pins systemd/generated/ == render(manifest) and runs in the pre-commit gate — manifest edits REQUIRE re-rendering or the commit fails; check for pre-existing drift on clean HEAD before assuming your change broke it.
- A failed `git commit` leaves files staged — a later commit picks them up under the wrong message; `git reset HEAD~1` (mixed) to redo split commits.
