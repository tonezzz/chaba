# Dispatch outcome — audit-miss-education-lesson-write-timeout

## Result: DONE — lesson landed and verified in both stores

Retried the Education lesson upsert for topic `missed-job-sweep-and-safe-opencode-ha-tabs` via the supported door (`scripts/lesson-add.py --no-th`, level `working`, source `chat`).

- **Write:** `created lesson-4dd48148b1be (Education:Missed-Job-Sweep-And-Safe-Opencode-Ha-Tabs)` — HTTP 200 on the first retry.
- **Education store read-back:** `POST /lesson {op:get, topic:...}` returns the full wikitext body, `wiki_title`, `url`, and meta (`learned_at=2026-11-24`, `next_review=2026-12-01`, `status=open`, `no_th=true`, `level=working`). Page: https://wiki.h3.gizmo-thailand.com/index.php?title=Education%3AMissed-Job-Sweep-And-Safe-Opencode-Ha-Tabs
- **MDDB mirror read-back:** `chaba-lessons|lesson-4dd48148b1be|en` present on the :11027 content plane with matching meta (`store=wiki`, `no_th=1`) and full contentMd.

## Why the 2026-10-29 failure cannot recur the same way

The original failure was HTTP 502 on the upstream **WordPress** GET/read timeout. The lesson store cut over on 2026-11-06 (`WIKI_EDUCATION_WRITE=wiki`): `do_lesson` now writes the MediaWiki `Education:` namespace as the ONLY store — the WP CPT is a frozen archive and is not touched at all. Read defaults follow the write flag, so `op:get`/`op:list` with no `source` now read wiki. Verified live: `op:list` returns "222 wiki lessons" and `op:get` resolves `Education:` titles. The WP lookup-health gate in the spec was checked anyway (board-api reads respond cleanly and fast) before writing.

## Content provenance (important caveat)

The original 2026-10-29 session transcript is not on this host, so the exact drafted HTML could not be recovered. The lesson body was reconstructed faithfully from the durable artifacts of commit `dd8a1684d2` ("fix(ha): render DevNest report and audit missed jobs"): `docs/kb/missed-job-sweep.md` (9-step procedure + thresholds), `docs/ssot/jobs/home-assistant/2026-10-29-ada-devnest-tab-visual-fix.yml` (the safe HA-tab mutation pattern: prove blank via PlayLive, reuse existing viewer key, idempotent validated mutate(), push-dashboard.py + read-back + sanitized snapshot), and the job/SSOT records. The repo runbook was NOT treated as a substitute — this is a standalone Education lesson that also carries the procedure inline.

## Secondary finding — filed as AUD-0044

`dd8a1684d2` is stranded on `origin/fix/ada-devnest-tab-render` (never merged; merge-base ~530 commits behind master). Master is missing the runbook, the `ssot.procedures.yml` `missed-job-sweep` entry, repeat-asks/frustration-procedure updates, both job SSOT records, `mutate-ada-ha-devnest-tab.py`, and its test. The LIVE fix did land — master's `ada-ha-chaba-admin-current.json` snapshot shows the devnest iframe on the CMS `embed=1#/devnest-visual-map` URL — so only repo artifacts are missing. Carded as `land-stranded-fix-ada-devnest-tab-render-05b20f` (AUD-0044, backlog) with a cherry-pick-over-merge recommendation. The new lesson's "Durable artifacts" section names these paths and flags the branch, so it stays honest until they land.

## How to verify

- `curl -X POST https://idc03.taila0626a.ts.net:10000/lesson -d '{"op":"get","topic":"missed-job-sweep-and-safe-opencode-ha-tabs","from":"devin"}'` — returns slug `lesson-4dd48148b1be` + full content.
- MDDB: `chaba-lessons` key `lesson-4dd48148b1be` (verified above).
- Card comms on `audit-miss-education-lesson-write-timeout` record the same evidence.

lessons:
- The 2026-10-29 WP-502 failure mode is obsolete: WIKI_EDUCATION_WRITE=wiki since 2026-11-06 routes /lesson writes to the MediaWiki Education: namespace; the WP CPT is a frozen archive. Retry specs written against the WP era should be re-checked against the current store before gating on "WP lookup healthy".
- Lesson upsert keys on topic slug → wiki_title via lesson_wiki_title(); op:get by topic resolves the same page, so retries are idempotent (re-file preserves learned_at/next_review/status).
- Dispatch worktrees lack prior-session transcripts; when a retry needs lost draft content, reconstruct from the durable artifacts named in the originating job/commit rather than treating the miss as unrecoverable.
- A "committed in the repo" claim in an audit card can mean "committed on an unmerged branch" — verify reachability from origin/master (git ls-tree/merge-base), not just existence in git history.
