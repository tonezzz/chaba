# Dispatch outcome — ssot-research-verifier-semantic (KNB-1029)

## What was done

Evidence confirmed and the recommended fix implemented.

- **Evidence verified**: the KNB-1029 artifact (qwen3:8b via
  `ollama-qwen38b-kkmac`, 2026-10-30) is archived in
  `evals/opencode-lane/reports/2026-11-07-session-audit.json`
  (session `ses_e72e4865dffeSHpW6C3zDQtnTG`). It cited real paths
  (AGENTS.md, docs/ssot/infrastructure/ssot.mcp.yml) while claiming
  `/etc/hosts` + MCP tools; truth is `ssot.audit.hosts.yml` +
  `stacks/idc03/litellm/config.yaml` (both confirmed present).
- **Bug reproduced**: replaying that artifact through the OLD
  `verify.py` returns `verdict: pass` — citation-existence gate only.
- **Fix (card-recommended option)**: quote-verification. Every
  citation's `note` must now contain a quoted string (double/curly/
  backtick/single quotes, whitespace-normalized, >=8 chars) that
  appears verbatim in the cited file. No quote or quote-not-in-file
  fails closed with reason `no quote` / `quote not in file`.
- Chose quote-verification over a judge pass / human-review-only per
  the card's own recommendation: deterministic, no new infra.

## Files changed (commit 84adc57090 on dispatch branch)

- `evals/opencode-lane/profiles/ssot-research/fixture/verify.py` —
  new `every citation quote verified` check + `_quotes`/`_file_norm`.
- `evals/opencode-lane/profiles/ssot-research/fixture/prompt.md` —
  rules + checklist now require verbatim quotes per citation note
  (required, else every run fails closed).
- `evals/opencode-lane/profiles/ssot-research/fixture/task.yaml` —
  contract documents the quote requirement.
- `tests/devnest/test_ssot_research_verify.py` — 6 tests incl. the
  KNB-1029 artifact replay.
- `docs/ssot/jobs/devnest/2026-11-24-ssot-research-verifier-quote-check.yml`
  — runbook/trail incl. options-weighed.

## Verification

- `python3 -m pytest tests/devnest/test_ssot_research_verify.py -q`
  -> 6 passed.
- Manual replay: old verifier on archived KNB-1029 artifact -> pass
  (bug); new verifier -> fail (`no quote` x2).
- Positive case with real quotes -> pass; fabricated quote -> fail
  (`quote not in file`); whitespace-normalized cross-line quote ->
  pass.

## Residual gap

A note can quote real text that doesn't support the claim — quote
existence != claim-truth either, but it is the checkable floor; full
semantics still needs the judge pass or human review (same residual
the OPS-1017 fix accepted). `info-find` profile has a similar
citation-resolvability check and could lift this helper later.

lessons:
- verify.py resolves REPO via `Path(__file__).parents[5]` — to replay an OLD verifier version, copy it into the fixture dir under a temp name; running it from elsewhere silently resolves the wrong root and produces bogus path failures.
- ssot-research citations are `{path, note}` objects — quote-verification keys off `note`, so prompt.md and task.yaml contract had to change in lockstep or every run fails closed on missing quotes.
- The archived KNB-1029 artifact lives in evals/opencode-lane/reports/2026-11-07-session-audit.json (session audit JSON `text_tail`), not in evals/opencode-lane/out/ — search reports/ when hunting dispatch evidence.
