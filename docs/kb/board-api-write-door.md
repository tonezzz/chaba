# board-api — the unified write door

**Status:** deployed (card `nest-api-unified-mutation-service`, OPS trail
`docs/ssot/jobs/infrastructure/2026-10-23-board-api-unified-mutations.yml`).
Service: `chaba-board-api.service` on idc03, `127.0.0.1:8787`, tailnet front
`https://idc03.taila0626a.ts.net:10000` (Caddy strips `/apps/board-api/`).

## Rule

**Watchers watch, one door writes.** Every mutation an agent needs — kanban
cards, WP lesson/nest_job CPTs, ada-cms-pages report pages, focus-inbox
entries — goes through board-api over HTTP. Agents and runners never hold
WP app passwords or mddb credentials; only the service host has
`~/.config/secrets/wp-boards.env`. Same reason Colab stays credential-free.

## Endpoints (after prefix strip)

| Path | Body | Writes |
|---|---|---|
| `/card` | `{id?, title, column?, spec?, report?, action?, queue?, ...}` | new card YAML + commit |
| `/comment` | `{id, from, text}` | card comms append |
| `/request` | `{id, ask, options?, suggested?, to?}` | card `requests[]` |
| `/respond` | `{id, request_id?, answer|option}` | answer a request/ask |
| `/action` | `{id, do: queue|close|hold|retry|claim|move|finish}` | card state |
| `/pipeline` | `{id, opt_in?|pipeline?|stage+status}` | CI status block |
| `/patch-relay` | `{id, head, branch?, bundle}` | git bundle spool |
| **`/lesson`** | `{topic, content, level?, source?, next_review?, status?, no_th?, from?}` | WP `lesson` CPT upsert by slug `lesson-<md5(topic)>` + auto-Thai section |
| **`/job`** | `{slug, title?, status?, comms?|note?, parent?, kind?, host?, pack?, runner?, result_ref?, error?, meta?}` | WP `nest_job` CPT upsert (ada-nest queue mirror) |
| **`/report`** | `{query}` \| `{slug, note, lang?}` \| `{title|slug, content_md, meta?}` | ada-cms-pages search / session-log append / create |
| **`/inbox`** | `{text, label?, priority?, tags?, missing_info?, subtasks?, session?, owner?, safe_to_parallel?}` | `docs/ssot/focus-inbox/<ts>-<slug>.yml` + commit |
| **`/publish`** | canonical `PublicationEvent` (below) \| `{op:"sinks"}` \| `{op:"drain"}` | fan-out to sink adapters: `job`/`lesson`/`report`/`news`/`telegram`/`board`/`json` |

## Endpoint notes

- **`/job`** — `status` ∈ `queued|claimed|running|done|failed|stalled|
  cancelled`; `comms`/`note` appends `{at,from,text}` to a JSON log in
  `meta.comms` (cap 200); `parent` accepts a post id or a sibling job slug
  (job trees). `from` accepts actors or daemon/host names (`queue-mgr`,
  `tony-dell`). queue-mgr on dell mirrors `gdrive:ada-nest` queue/packs
  state through this — Colab workers and watchers never write.
- **`/lesson`** — same semantics old `scripts/lesson-add.py` had (which is
  now a thin CLI client of this endpoint): upsert by topic slug,
  `learned_at`/`next_review`/`status` preserved on re-file, Thai section
  appended unless `no_th` (gemini flash-lite, best-effort — a translation
  failure returns EN-only, never a failed write).
  The board-api Thai translation now uses the LiteLLM virtual key
  `LITELLM_KEY_MDDB` and the explicit free-only deployment
  `gemini-3.5-flash-lite-free`; it has no paid fallback. The Gemini REST
  helper accepts a per-call gateway URL override so this path does not
  depend on a process-global `GEMINI_BASE_URL`. Missing key, gateway error,
  or free-tier quota exhaustion still degrades to an English-only lesson.
- **`/report`** — the report-integration duty: `mode` optional, inferred
  from fields. `query` → candidate slugs; `slug+note` → session-log append
  (reuses `cms-report-note.py` logic — managed block + writer-contract
  meta merge + index regen); `title+content_md` → create a new page.
- **`/inbox`** — lands a `docs/ssot/focus-inbox/` YAML in the TEMPLATE
  shape; runs under the card flock with the same atomic-write +
  immediate-commit discipline as cards.

## /publish — the provider-neutral publication door

`POST /publish` takes one canonical `PublicationEvent` and fans it out
to registered sink adapters (`scripts/board/publication.py`). The
legacy endpoints are the compatibility adapters onto the same provider
writes — `/publish` routes through `do_job`/`do_lesson`/`do_report`
themselves, so WP is only one adapter and any second sink receives the
same event. Agents still never call WP REST or hold credentials.

**Event:** `kind` (progress|milestone|report|lesson|news|alert),
`title`, `source` (producer, required), `body` (required for
lesson/report/news), `project`/`job`/`card` refs, `parent`,
`evidence[]` (required for `news`), `confidence`
(observed|measured|verified — `public` news requires `verified`),
`visibility` (private|members|public — **private-first default**),
`audience[]`, `media[]`, `occurred_at`, `event_id`,
`idempotency_key` (auto-derived if absent — identical events dedupe),
`sinks[]` (explicit subset; else kind defaults), `force`, `meta{}`
(provider extras: `job_status`, `topic`, `level`, `report_slug`,
`tg_thread_id`, …).

**Kind → sinks (defaults):**

| kind | sinks | note |
|---|---|---|
| progress | `job`, `board` | heartbeat-class: throttled, never TG |
| milestone | `job`, `board`, `telegram` | |
| report | `report`, `board` | dossier needs `project` slug |
| lesson | `lesson` | Education CPT |
| news | `news`, `board`, `telegram` | evidence required |
| alert | `telegram`, `board`, `job` | |

**Guards:** idempotent on `idempotency_key` (deduped replies carry the
stored receipts); outbox under `~/.local/state/board-api-publish/`
retries failed sinks (30s×2ⁿ ≤30m, dead-letter after 5); capability
checks per sink (`{op:"sinks"}` reports surfaces/kinds/evidence);
noise policy throttles progress per (sink,topic) 15m, telegram floor
10m/topic, identical alerts 60s (`force:true` bypasses noise only —
never visibility); visibility gates sinks by surface class (private →
board+json only; members → +WP private posts/TG; public → +publish
status). Receipts are per-sink `delivered|queued|skipped|suppressed`
with reasons — a `502` still means the door itself failed.

State: `$BOARD_API_PUB_STATE` (default `~/.local/state/board-api-publish/`):
`delivered.json`, `events.jsonl` (ledger), `outbox.jsonl`, `dead.jsonl`,
`noise.json`. Env: `PUB_TELEGRAM_URL`, `PUB_PROGRESS_MIN_S`,
`PUB_TG_MIN_S`, `PUB_ALERT_MIN_S`.

```bash
curl -sX POST https://idc03.taila0626a.ts.net:10000/publish \
  -H 'Content-Type: application/json' -d '{
    "kind":"milestone","title":"Pilot A passed","job":"fl-pilot-a",
    "card":"devnest-fl-pilot-report","project":"devnest",
    "source":"devin","visibility":"members","confidence":"verified",
    "body":"Free lane merged with zero tokens.",
    "evidence":["docs/reports/devnest-free-lane-pilot-a.md"]}'
```

## Auth, locks, errors

- Same write gate as cards: `Tailscale-User-Login` (tailnet), loopback
  caller, or the CF edge key. Machine-to-machine tailnet calls carry the
  node identity automatically.
- Remote-backed endpoints (`/lesson`, `/job`, `/report`, `/publish`)
  serialize under `/tmp/board-api-wp.lock` — NOT the card flock — so a
  45s WP round-trip never stalls `/comment`. `/inbox` uses the card
  flock (repo write); `/publish`'s `board` sink takes the card flock
  nested inside WP_LOCK (order is always WP_LOCK→LOCK, never reversed).
- Errors: `400` validation, `403` identity, `502` upstream (WP/mddb down —
  the body names the failing route), `500` unexpected. WP credentials are
  read lazily per call — a missing `wp-boards.env` fails only the
  WP-backed endpoints, not the service.

## Callers

```bash
# lesson (was: scripts/lesson-add.py with wp creds — now credless)
python3 scripts/lesson-add.py --topic "X" --content-file /tmp/l.html

# direct POST
curl -sX POST https://idc03.taila0626a.ts.net:10000/job \
  -H 'Content-Type: application/json' \
  -d '{"slug":"thonburian-bench","status":"done","kind":"pack",
       "comms":"finished in 98s","from":"queue-mgr"}'
```

`scripts/lesson-add.py` resolves the door via
`dispatch_repos.board_api_base()` (`BOARD_API` env →
`https://idc03.taila0626a.ts.net:10000`).

## Deploy dependency

`/job` needs chaba-boards **v0.9.0** (`nest_job` CPT) deployed to WP —
repo change is in `integrations/wp-boards/chaba-boards.php`; deploy via
`scripts/wp-boards/deploy-plugin-zip.sh` from tony-omen (wp-admin upload,
Tony-approved per plugin bump). Until then `/job` returns 502
`rest_post_invalid…` — `/lesson`, `/report`, `/inbox` are independent of it.

Tests: `python3 scripts/board/board-api.py --selftest` +
`tests/board/test_board_api_mutations.py`.
