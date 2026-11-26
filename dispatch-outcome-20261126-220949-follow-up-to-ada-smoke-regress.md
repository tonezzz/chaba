# Dispatch outcome — ada-smoke-scenario-expectation-rot-fixes

Card: `ada-smoke-scenario-expectation-rot-fixes` (ADA-1456)
Follow-up to `docs/ssot/jobs/ada/2026-11-26-smoke-regressions-triage.yml`.

## What changed

All fixes landed in the **ada-voice** repo — worktree
`~/CascadeProjects/ada-voice-wt-smoke-fixes`, branch
`dispatch/20261126-smoke-expectation-rot`, commit `6c0aba5`
(**committed, not pushed** — merge/deploy is the dispatcher's call).
Trail doc: `docs/ssot/jobs/ada/2026-11-26-smoke-expectation-rot-fixes.yml`
in this worktree.

1. **ada_opencode_control.yaml turn3** — reworked to the approval-handshake
   contract: `no_calls: [ada_opencode_dispatch]` + `response_contains_any`
   (receipt/approval/confirm/preflight/can't...). A real receipt needs a
   card envelope + board ask + Tony's yes inside the 600s TTL — not
   stageable in a smoke turn, so gate refusal is the contract under test.
   **Extra find:** turn2 used `calls_not:`, which is NOT a scenario-live
   key (silently ignored) — corrected to `no_calls:`.
2. **auto_report_worthy.yaml turn1** — `calls_any` widened to
   `[ada_memory_search, cms_read, cms_get_page, cms_list_pages]`; comment
   updated (canonical source = `auto-report` CMS page).
3. **cms_public_url_lane.yaml** — parameterized per lane via new
   `{public_tenant}`/`{cms_collection}` tokens (`ADA_PUBLIC_TENANT` /
   `ADA_CMS_COLLECTION` env, defaults `tony-ha`/`ada-cms-pages` = the
   ada-dev lane the smoke suite actually runs on). URL assertion and
   cleanup collection now follow the lane.
4. **cms_translate.yaml** — assertions kept as the regression tripwire;
   comments record the finding. **Root cause of the missing
   `'lang':'th'`:** `lang` is in the declared schema (enum en/th) but was
   named nowhere the model reads — not in tool_guide's
   `cms_publish_page` entry, not in DEFAULT_ADA_INSTRUCTIONS — so Thai
   publishes upserted the EN doc. Fixed by documenting `lang=` in
   `backend/tool_guide.yml` (the repair-hint surface attached on arg
   misses). This is a prompt-surface change beyond the two listed file
   globs — flagged for review.
5. **scripts/scenario-live.py REAL BUG** — added `_mddb_base()` routing
   (`ada-cms-`/`chaba-`/`kb-` prefixes + CMS exact names →
   `$MDDB_CMS_URL` default `http://100.102.134.91:11027/v1`, mirroring
   `backend/mddb_client.py`), applied to **all three** MDDB paths:
   `run_cleanup`, `run_seed`, `run_seed_evictions`. The same bug in
   `run_seed` means `kk_cms_only_seeded_recall`'s
   `ada-cms-pages-kk-dev` seed could never have worked.

## Result / how to verify

- `python3 -m py_compile scripts/scenario-live.py` clean; all touched
  YAMLs parse; `_mddb_base` + `_expand_tokens` exercised via importlib
  (websockets absent in this env — live pytest needs the repo venv).
- Live verification = next hourly smoke run on ada-dev after merge +
  `deploy-ada.sh` on idc03: expect `'lang': 'th'` in cms_translate
  results, cms_public_url_lane cleanup to actually delete
  `ada-cms-pages/kk-site-test`, and no more cms_* cleanup 404s.

## Open item for Tony (board request raised)

Delete/unpublish stray **public** page `ada-cms-pages/kk-site-test`
(live at surf-thailand.com/tony-ha/kk-site-test.html since 2026-10-11)
plus leftover `translate-probe{,-de}` test docs. Caveat posted with the
request: once this branch deploys, the next cms_public_url_lane run will
delete kk-site-test via cleanup regardless — "no" means keep/unpublish.

lessons:
- scenario-live.py expect keys are no_calls/calls_any — `calls_not` does not exist and fails silently.
- cms_* tool names in scenarios can stay legacy (cms_get_page) — LEGACY_TOOL_ALIASES expands them to cms_read/cms_edit at check time.
- Lazy tool schemas ship {} on the wire; arg-shape repair depends on tool_guide.yml naming every arg — a schema enum the guide omits is a guaranteed miss.
- MDDB has two planes; any script posting per-collection must route like backend/mddb_client.is_cms_collection — seed paths had the same bug as cleanup.
- Cross-lane scenario assertions must be token/env-parameterized ({public_tenant}/{cms_collection}) — hardcoding kk-ha on the tony lane is what hid a public fixture for 6 weeks.
