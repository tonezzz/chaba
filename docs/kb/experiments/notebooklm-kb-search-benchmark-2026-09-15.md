# NotebookLM vs MDDB KB search benchmark

Date: 2026-09-15
Notebook: `fdfd3483-6b7e-4cb0-85f3-7f060698769c` (Chaba KB search benchmark)
MDDB collection: `infrastructure-ssot`

## Sources ingested into NotebookLM

| Source | NLM source ID | Size |
|---|---|---|
| AGENTS.md | 3230c2de-07c8-44a0-a66f-aa846f387141 | 20K |
| README.md | b2d9ecf1-0123-44a1-8815-5496192a3682 | 8.6K |
| ssot-apps | f112d9b0-b529-4b70-b47f-dc5ee2fdb71e | 126K |
| ssot-top | 19d4ebd3-a830-49e7-b855-e95f238f3e44 | 505K |
| ssot-infrastructure chunks | c916c8c0, b30b932b, 2e2077af | 3 × 200K |
| kb chunks | 572981d2, c5a49947, 467ed4fa, 24e33814 | 4 × 233K |

Total: 13 sources, ~2.2 MB of text.

## Test questions

1. What is the Tailscale IP of tony-dell?
2. How do I restart the NotebookLM REST auth refresh?
3. Where does Caddy serve the public apps from on tony-dell?
4. What is the nlm-add workflow for adding SSOT sources to NotebookLM?
5. How do I fix devin-desktop after a crash on tony-dell?
6. Which Home Assistant token file should I use for michael-ha?
7. How do I deploy a new card bundle to michael-dev?
8. How do I add a new app to the public apps page on tony-dell?

## Results summary

| # | Question | MDDB top hit | NotebookLM answer | NLM time |
|---|---|---|---|---|
| 1 | Tailscale IP of tony-dell | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: `100.68.142.13` | 38.6s |
| 2 | Restart NotebookLM REST auth refresh | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: `systemctl --user start notebooklm-rest-auth-refresh.service` or `~/.local/bin/notebooklm-rest-auth-refresh` | 42.8s |
| 3 | Caddy public apps root | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: `~/.config/caddy/public/apps/` | 42.1s |
| 4 | nlm-add workflow | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: convert, upload to Drive, add by Drive ID, write manifest | 43.4s |
| 5 | Fix devin-desktop crash | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: `nohup` X display restart + stale scopes + watchdog + logs | 55.6s |
| 6 | michael-ha token file | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: `~/.config/secrets/ha-michael-live.env` | 48.6s |
| 7 | Deploy card bundle to michael-dev | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: worktree, tsc, `deploy-card.sh`, verify, sync SSOT | 68.7s |
| 8 | Add app to public apps page | `apps-ssot.apps.ada_ha` (irrelevant) | Correct: add to `stacks/web/public/apps/`, run `apps-yml-generate.py`, `apps-health-sync` deploys | 48.9s |

## Scorecard

| Criteria | MDDB (current) | NotebookLM |
|---|---|---|
| Accuracy | 0/8 | 8/8 |
| Citation / source tracking | key + title only, mostly wrong | inline citations with exact source IDs and quoted text |
| Completeness | requires user to read retrieved doc and synthesize | full step-by-step answer with context |
| Speed | ~0.05s per query | ~40-70s per query |
| Natural language handling | poor; returns the same 3 app docs for every question | excellent; handles rephrasing and procedure |
| Setup cost | already running, incremental | requires auth, Drive upload, ~10 min ingest for full KB |

## Key findings

- **MDDB semantic search** in the `infrastructure-ssot` collection returned the same 3 documents (`apps-ssot.apps.ada_ha`, `apps-ssot.apps.ada_pi`, `apps-ssot.apps.aihub`) for every question, regardless of the query. The retrieved documents were not relevant to any of the test questions.
- **NotebookLM** correctly answered all 8 questions with grounded, cited responses. It synthesized information across multiple sources (AGENTS.md, ssot-infrastructure, ssot-values, kb docs) and returned exact commands, paths, and values.
- **Trade-off**: NotebookLM is ~1000x slower per query and requires manual ingestion/auth, but produces actionable answers. MDDB is near-instant but currently does not surface the right documents for natural-language questions.

## Recommendation

Use a **hybrid** approach:

1. **Primary Q&A**: use NotebookLM for deep/procedural questions that require synthesis and exact commands.
2. **Quick exact lookups**: keep MDDB for metadata-aware lookups (e.g. `key`, `title`, `original_path`) and SSOT validation.
3. **Improve MDDB**: investigate why semantic search is returning the same top hits; likely needs re-embedding, query re-weighting, or a separate `kb-qa` collection focused on prose/docs.
4. **Re-ingest**: run `apps-health-sync.timer` daily to keep the NotebookLM public app KB in sync; re-run the `merge-kb-for-nlm.py` + `bench-kb-search.py` workflow when the KB changes significantly.
