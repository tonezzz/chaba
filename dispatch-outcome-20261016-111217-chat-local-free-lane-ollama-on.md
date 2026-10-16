# chat-local-free-lane — attempt 3 outcome

## What this run did

Attempt 2's work was verified-good; the merge was held by the test
gate, not by the card's changes. This run cherry-picks attempt 2's
commits (`c02db2755` feat + `625ac976c` outcome doc) onto this branch
and fixes the **four** independent causes of a red suite — the reported
one plus three that `-x` had masked behind it.

## The merge-gate failure, actually fixed

| Cause | Fix |
|---|---|
| `git clone` of ~/CascadeProjects/ada-voice takes 4m37s (86M-object pack over `/` = rotational HDD @97% full) vs 120s test timeout | `--depth 1` + `file://` URI in `test_cast_loop_breaker.py` + `test_correction_command.py` → 4.7s |
| Staged-drop patch tests demanded forward `git apply` after drops 6/7/8 had already merged into ada-voice (`02c5058`, `8f8f488`) | New `tests/ada/_drops.py` tri-state resolver: **applied** / **merged** (reverse-applies → test live file) / **diverged** (warn + live file; guard fails only if NO sibling merged = genuinely rotted pending drop). Wired into all six drop-test files |
| `dep_stubs.install()` leaked fabricated `fastapi`/`starlette` into `sys.modules`, poisoning `test_obsidian_app`'s `fastapi.testclient` import | `test_line_reply_routing` snapshots `sys.modules` and pops additions |
| `test_claim_order` sampled live host load via `overloaded()` — busy box ⇒ zero claims ⇒ empty list assertion | stubbed `overloaded = lambda: False` (order is under test, not the load gate) |
| Live `_images_from` returns `(url, cap, kind)` triples (post-merge video-bubble evolution) | assertion updated to merged contract |

Also: `integrations/ada-voice/README.md` drop list now marks drops 5–8
**already deployed** (matching the drops 4/9 convention), and a job doc
lands at `docs/ssot/jobs/kanban/2026-10-16-drop-patch-tristate-guard.yml`.

## Card work itself (inherited from attempt 2, re-verified)

- `scripts/ada/litellm_chat.py` shared gateway caller; `news-digest.py`
  EN synthesis via `chat-local` w/ gemini fallback + Thai via `summary`
  alias; `wp-comment-sync.py` `classify_situation_intent` free-text
  fallback; `kanban-brief.py` bearer-key support; idc02 ollama quadlet +
  stack manifest; litellm config mirror + SSOT (`ssot.llm-gateway.yml`,
  `ssot.jobs.yml` kanban-brief env → gateway + litellm-chaba.env).

## Verified

- `python3 -m pytest tests -x -q` → **370 passed, 38 skipped, 50s**
  (gate budget 240s; previously 9F + 26E).
- `ssot-validate-all.mjs` → 2487/2487 valid, 0 errors.
- `python3 -m compileall` on `litellm_chat.py` + `_drops.py` — clean.

## Not pushed

Per dispatch rails the branch is committed but not pushed; merge-sweep
picks it up.

## lessons:
- a `-x` test gate reports only the first red — fixing it can unmask a queue of pre-existing failures; run the full suite without `-x` before claiming green.
- `git clone <local-path>` across filesystems still packs the whole object store; `--depth 1 file://<path>` is ~60x faster and immune to object-store size.
- staged-patch drop tests rot the day the drop merges upstream — resolve patches tri-state (applied/merged/diverged), never bare `git apply`.
- ada-voice `dep_stubs.install()` mutates global `sys.modules` — snapshot and pop additions in a `finally` or fake `fastapi` poisons later imports.
- runner-agent tests must stub `overloaded()`; live `loadavg` sampling makes them flaky on busy hosts.
