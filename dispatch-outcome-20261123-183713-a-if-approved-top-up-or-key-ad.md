# Dispatch outcome — rainy-day-spend-decisions (OPS-1256), attempt 3

## What changed / was found

**(a) OpenRouter + LiteLLM**
- The $10 top-up was already done by Tony (OR `/key` shows the 1000/day
  free-model tier; ~$0.98 remains under the key's separate $1/WEEK spend
  cap — Tony can raise that cap at openrouter.ai/keys if bigger paid OR
  traffic is wanted).
- Added `or-deepseek-v4-flash` (`openrouter/deepseek/deepseek-v4-flash`,
  $0.09/$0.18 per Mtok) to `stacks/idc03/litellm/config.yaml`, deployed
  to idc03 (`~/.config/litellm/config.yaml` + `systemctl --user restart
  litellm`, health OK), and appended it to the `chaba` virtual-key
  allowlist (43→44). Live probe via `LITELLM_KEY_CHABA` returns 'ok';
  `tool-call` verified still serving.
- Updated `docs/ssot/infrastructure/ssot.llm-gateway.yml`
  (`openrouter_paid` lane) and tony-dell's opencode provider map via
  `sync-opencode-models.py --write`.

**Code-corpus bench** (`~/evals/config.ds-v4-code*.yaml` on tony-dell,
tasks t1-terrology-sea-predicate + m1-behavioral — same corpus as the
11-09 zen-code run):
- `or-deepseek-v4-flash`: **2/2 pass, final 1.0, $0.0196 avg/run, 389s
  avg** (m1 $0.033/725s, t1 $0.006/53s)
- `gemini-3.5-flash-lite` baseline: 2/2 pass, $0.675 avg/run, 853s avg
- `deepseek-v4.1-flash-free` (zen $0): t1 pass 83s, **m1 timeout at
  1500s** — free tier flaky on the heavy task, matching 11-09.
- Verdict: the paid flash lane is a viable cheap code brain — same
  score as baseline at ~1/34 cost and ~2.2× speed. Results JSON:
  `tony-dell:~/evals/results/20261123_115202_3d02ec.json` (+ .html).

**(b) Devin default model**
- `agent.model`: `swe-2-high` → `swe-2-flash-high` in
  `~/.config/devin/config.json` on all six dispatch hosts (idc02,
  tony-dell, idc03, tony-omen, mn01, tony-macbook).
- Verified live: a `devin --print` session on idc02 logged
  `resolved_model_uid=swe-2-flash-high` — the next session uses it.
- Correction to the card premise: `devin models list` shows the whole
  swe-2 family is Free now (only `-lightning` variants + claude/gpt are
  metered); flash-high is the cheaper-class free default, one-line revert.

**Trail**: `docs/ssot/jobs/devnest/2026-11-23-rainy-day-spend-decisions.yml`,
branch commits `f0589ac46b` + `f244d045a9` + outcome commit.

## Result

Card spec fully executed; total OR spend for the whole bench ≈ $0.04.

## Verify

- `curl -s http://100.102.134.91:4000/v1/chat/completions -H "Authorization:
  Bearer $LITELLM_KEY_CHABA" -d '{"model":"or-deepseek-v4-flash",...}'`
- `ssh idc03 'systemctl --user status litellm'` + health/liveliness
- `devin models list` (free slugs) + any new devin session log's
  `resolved_model_uid`
- bench: `~/evals/results/20261123_115202_3d02ec.json` on tony-dell

lessons:
- LiteLLM POST /key/update REPLACES the models list — never build the
  payload from a same-shell /key/info fetch (it can return empty and
  clobber the allowlist); snapshot the list to a file first, diff after.
- opencode v2.3.2 broke two things silently: `run --dir` is gone
  (positional directory arg now) and `{env:VAR}` in provider
  options.apiKey resolves empty -> 401 even when exported; `{file:path}`
  works — tony-dell now uses
  ~/.config/secrets/litellm-key.txt.
- Evals that "fail" in seconds with nonzero-looking scores are the
  verifier grading an untouched workspace — check phase_results error,
  not the score, before trusting a pass/fail table.
- `devin --print` refuses untrusted workspaces; pass
  `--respect-workspace-trust false` (devin-dispatch already does).
- nohup'd commands over ssh lose ~/.local/bin — export PATH explicitly
  before launching agent-cost-bench/opencode.
