# chat-local-free-lane — attempt 2 outcome

## What the card needed

Attempt 1 (2026-10-15) deployed the lane itself (ollama podman on idc02
serving qwen2.5:7b-instruct + nomic-embed-text; LiteLLM `chat-local`
alias on idc03 with ollama-llama3.2/colab-gemma3 fallbacks; verified
smoke). Its remaining work — and the reason it didn't merge cleanly —
was **caller adoption**, plus the repo copy of the gateway config and
SSOT were never synced to the deployed state. This run closes that.

## What changed

### Code (all fall back cleanly when the lane is down)

- `scripts/ada/litellm_chat.py` (new) — shared OpenAI-style
  `/chat/completions` + JSON caller. Creds: `LITELLM_URL`/`LITELLM_KEY`
  env, else `~/.config/secrets/mddb-gemini.env`, else
  `LITELLM_ENV_FILE`. Returns None on any failure.
- `scripts/ada/news-digest.py` — **news-digest synthesis**: EN fields
  (topic/brief/diffs) via `chat-local` (default; `NEWS_DIGEST_LLM=gemini`
  or any failure restores the legacy single-gemini path). `brief_th` is
  a separate small translate call through the gateway `summary` class —
  still gemini upstream per the card's "Thai on gemini", but on paid
  quota instead of the free key that was 429ing. Direct gemini is the
  last resort.
- `scripts/ada/wp-comment-sync.py` — **wp-comment classification**:
  when the regex command table misses on a news comment, a chat-local
  one-word intent classify (pin/watch/unpin/unwatch/none) runs first;
  ambiguity or failure -> digest lane exactly as before.
  `WCS_CLASSIFY=0` disables; transitions note `via chat-local` in the
  WP audit comment.
- `scripts/ada/kanban-brief.py` — **card triage**: prose "why now"
  layer gained bearer-key support (`KANBAN_BRIEF_LLM_KEY`/`LITELLM_KEY`)
  so it can ride the gateway; failure still falls back to the
  deterministic line.
- **situation summaries**: no separate call site — digests ARE the
  situation summaries (news-situation reads digest `brief`/`brief_th`),
  and its `ask` matching already uses ollama-nomic-embed (now
  load-balanced idc02+idc03). Covered by the digest change.

### Config / SSOT

- `stacks/idc03/litellm/config.yaml` — mirrored to live: `ollama-qwen7b`,
  second `ollama-nomic-embed` backend on idc02 (same model_name = LB,
  halves embed traffic off prod), `chat-local` job class + fallback chain.
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` — `ollama-idc02`
  provider, `chat-local` job class with adopter list, proof_lanes entry.
- `docs/ssot/infrastructure/ssot.jobs.yml` + rendered
  `systemd/generated/tony_dell/chaba-kanban-brief.service` (and the
  legacy `systemd/` copy) — prose lane moved off tony-omen phi3-gguf to
  `KANBAN_BRIEF_LLM_URL=http://100.102.134.91:4000/v1` +
  `chat-local` + `EnvironmentFile=%h/.config/secrets/litellm-chaba.env`.
- `stacks/idc02/ollama/{stack.yml,ollama.container}` — manifest +
  quadlet for the new service.
- Fixed pre-existing YAML syntax errors in
  `docs/ssot/jobs/infrastructure/2026-10-16-tony-dell-mcp-health-postboot-flap.yml`
  (unquoted `: ` in plain scalars — the SSOT validator was red).

### Live side effects

- idc02 ollama **rebound `0.0.0.0:11434` -> `100.123.163.11:11434`** —
  attempt 1 had an unauthenticated LLM API on the public IP — and
  converted from manual `podman run` to the host's quadlet convention
  (`~/.config/containers/systemd/ollama.container`, linger=yes,
  Restart=on-failure). Models intact.
- tony-dell: `~/.config/secrets/litellm-chaba.env` created
  (`LITELLM_URL` + `LITELLM_KEY`=CHABA virtual key, 0600); the
  re-rendered `chaba-kanban-brief.service` installed + daemon-reload.
  The unit's ExecStart runs the *served* checkout, so gateway calls get
  the auth header once this branch merges and the checkout pulls —
  until then llm_why 401s and silently falls back to deterministic
  lines (no breakage).
- idc03 callers need no env changes — `mddb-gemini.env` already carries
  `LITELLM_URL`/`LITELLM_KEY`.

## Verified

- `chat-local` alias: `LANE_OK` reply via CHABA key; MDDB key also
  works (attempt-1 smoke).
- `classify_situation_intent` 6/6: "keep an eye on this flood" ->
  watching, Thai "ช่วยเฝ้าดูข่าวนี้หน่อย" -> watching (regex misses
  that phrasing), "pin it up top" -> pinned, "stop tracking this now"
  -> clear, "interesting story" and narrative "glad they pinned that"
  -> none.
- `news-digest.synthesize` end-to-end: EN topic/brief/diffs from
  qwen7b, natural-Thai brief_th via gateway `summary`.
- `kanban-brief.llm_why` via gateway chat-local.
- `pytest tests/ada/test_news_situation.py`: 14/14 pass.
- `ssot-validate-all.mjs`: 2486 files all valid; `ssot-validate-refs.py`
  clean.
- ollama idc02: `/api/tags` + generate OK on tailnet IP; public IP
  connection refused.

## Not done / watch

- Embedding LB: `ollama-nomic-embed` now has two backends — first real
  traffic is worth a ledger glance (litellm usage UI) to confirm spread.
- digest quality: qwen7b EN output is adequate for topic/brief/diffs;
  if briefs degrade vs gemini, `NEWS_DIGEST_LLM=gemini` on the idc03
  unit reverts instantly.
- answer-sweep classify stays deterministic by design — free-text
  "decision" answers still need a human (LLM auto-execution of board
  verbs was judged out of scope/risky).

## lessons:
- check `git diff` between the repo's `stacks/idc03/litellm/config.yaml` and live `~/.config/litellm/config.yaml` when a card claims infra was deployed — attempt 1 left them diverged.
- ollama containers default-publish on 0.0.0.0 — always bind the tailnet IP (`-p <ts-ip>:11434:11434`); ollama has no auth.
- litellm virtual keys carry model allowlists — verify the specific key can call the new alias before wiring a caller to it.
- the free gemini key 429s under batch load; for gemini-quality output from batch jobs prefer a gateway alias (`summary`) over direct free-key calls.
- SSOT job docs written by earlier sessions may have unquoted `: ` in plain scalars — run `ssot-validate-all.mjs` before trusting a green tree.
