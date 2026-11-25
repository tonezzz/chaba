# board-api — the unified write door

**Status:** deployed (card `nest-api-unified-mutation-service`, OPS trail
`docs/ssot/jobs/infrastructure/2026-10-23-board-api-unified-mutations.yml`).
Service: `chaba-board-api.service` on idc03, `127.0.0.1:8787`, tailnet front
`https://idc03.taila0626a.ts.net:10000` — Caddy proxies the endpoint paths at
root (`POST /card`, `/comment`, `/action`, `GET /card/<id>`); there is NO
`/apps/board-api/` prefix (it 404s).

## Rule

**Watchers watch, one door writes.** Every mutation an agent needs — kanban
cards, WP lesson/nest_job CPTs, ada-cms-pages report pages, focus-inbox
entries — goes through board-api over HTTP. Agents and runners never hold
WP app passwords or mddb credentials; only the service host has
`~/.config/secrets/wp-boards.env`. Same reason Colab stays credential-free.

Reads are the mirror image: `docs/kb/board-api-read-door.md` — never
pull the 5 MB `/cards` dump for one fact; `/card/<id>` and
`/cards?<filters>&fields=` cover the narrow questions.

## Endpoints (after prefix strip)

| Path | Body | Writes |
|---|---|---|
| `/card` | `{id?, title, column?, spec?, report?, action?, queue?, ...}` | new card YAML + commit |
| **`/card-set`** | `{id, set:{lane?, executor?, tags?}, from, reason}` | routing-field edit on an existing card (see note) |
| `/comment` | `{id, from, text}` | card comms append |
| **`/attach`** | `{id, filename, payload|b64|data, from?}` (alias `/upload`) | file/photo evidence → `docs/ssot/kanban/attachments/<id>/<file>` + comms link |
| `/request` | `{id, ask, options?, suggested?, to?}` | card `requests[]` |
| `/respond` | `{id, request_id?, answer|option}` | answer a request/ask — idempotent: re-posting the same answer returns `already answered` (200), a different one needs `reopen:true` |
| `/action` | `{id, do: queue|close|hold|retry|claim|move|finish}` | card state |
| `/pipeline` | `{id, opt_in?|pipeline?|stage+status}` | CI status block |
| `/patch-relay` | `{id, head, branch?, bundle}` | git bundle spool |
| **`/lesson`** | `{topic, content, level?, source?, next_review?, status?, no_th?, from?}` | WP `lesson` CPT upsert by slug `lesson-<md5(topic)>` + auto-Thai section |
| **`/job`** | `{slug, title?, status?, comms?|note?, parent?, kind?, host?, pack?, runner?, result_ref?, error?, evidence?, verified?, meta?}` | WP `nest_job` CPT upsert (ada-nest queue mirror) — status writes follow `JOB_TRANSITIONS`; `done` requires `result_ref` + verified evidence (OPS-0923) |
| **`/report`** | `{query}` \| `{slug, note, lang?}` \| `{title|slug, content_md, meta?}` | ada-cms-pages search / session-log append / create |
| **`/inbox`** | `{text, label?, priority?, tags?, missing_info?, subtasks?, session?, owner?, safe_to_parallel?}` | `docs/ssot/focus-inbox/<ts>-<slug>.yml` + commit |
| **`/publish`** | canonical `PublicationEvent` (below) \| `{op:"sinks"}` \| `{op:"drain"}` | fan-out to sink adapters: `job`/`lesson`/`report`/`news`/`telegram`/`board`/`json` |
| **`/opencode-command`** | `{op: preview\|validate\|publish\|sync\|verify, name: ada, content?, confirm?, expect_sha?}` | allowlisted OpenCode command file — canonical write + commit queue + atomic idc02 deploy + sha verify (runbook: `docs/kb/opencode-command-publisher.md`) |
| **`/wiki/page`** | `{title|wiki_title, wikitext|text, summary?}` | guarded raw wiki page write — `Education:`/`Reports:`/`Infrastructure:` titles + configured support templates only |
| **`/wiki/extension`** | `{action: list\|install\|enable\|disable, name?, confirm?}` | MediaWiki extension control via wiki-side Springboard — allowlisted names only, `confirm:true` on mutations, Special:Version + receipt per change |

## Endpoint notes

- **`/card-set` — the routing-field door** (card
  `board-api-card-lane-executor-edit`): corrects `action.lane`,
  `action.executor`, and `tags` on an existing card — no other card
  fields are admitted (workflow fields — `column`, `requests`, `comms`
  — are human/producer-owned and move via `/action`, `/request`,
  `/comment`). `lane` must be in the `/card` whitelist
  (`LANE_MODELS ∪ LANE_EXECUTORS`, minus lanes the catalog
  `infrastructure/ssot.devnest-lanes.yml` marks removed/retired) —
  **`devin` is NOT a lane**: `executor=devin` is how you pin devin.
  `executor` must be in `dr.EXECUTORS`. An empty string clears the
  field (unpin → the queue-time classifier decides). `tags` takes a
  list (replace; ≤20, each ≤40 chars) or `{add:[], remove:[]}`. A
  non-empty `reason` is required — every edit appends
  `routing edited: <fields> by <from>: <reason>` to comms for audit.
  Refused (400) while `action.status` is running or a runner holds the
  claim; the write runs under the card flock so it can't race a claim.
  An explicit `lane` set drops `lane_source`, making it author-set —
  it wins over `_apply_classify_at_queue` instead of being
  re-classified on the next queue. CLI:
  `board-cli.py card-set CARD --reason "why" [--lane L|''] [--executor E|''] [--tags a,b|--tag-add a --tag-remove b]`.
- **`action.verify_*` — the held-out verifier contract** (card
  `doc-draft-verifier-semantic-gap`, 2026-11-24): `/card` admits
  `verify_contains`, `verify_sections`, `verify_regex`, and
  `verify_min_terms` on `action` — the doc-draft/artifact-write
  verify.py fixtures read them live off the card at verify time.
  Shapes are validated at the door (sentinels/regex = string or ≤20
  strings ≤300 chars, regexes must compile; `verify_min_terms` =
  `{terms, at_least}` or a bare term list). Before this they were
  silently dropped — no card could declare a sentinel via the API
  (the OPS-1014 miss). See `evals/opencode-lane/PROCEDURE.md`.
- **`/request` options** — `options[]` entries are strings or dicts
  `{id, label, action?}`. A dict option lets the emitter declare the
  answer's consequence at request time: when the answer picks that
  option, `answer-sweep.py` executes `action` verbatim —
  `queue|retry|close|hold|none` (same set as `OPTION_ACTIONS` in
  board-api and `ACTIONS` in answer-sweep). The door rejects dict
  options with no `id`/`label`/`v`/`d` and any `action` outside that
  set — a bad action would dead-letter the answer silently (KNB-0180).
  String options keep working unchanged: the answer's first word is
  looked up in the sweep's VERBS table, and decision answers stay
  flagged for human triage. `board-cli.py request` exposes this as
  `--option 'id|label|action'` (repeatable; action optional).
- **`/action do=queue|retry` and `/card queue:true|on_exists:queue`** —
  human-owned actions are never armed as `action.status=queued`.
  `action.type=manual`, `action.executor=manual`, an explicit
  `action.lane=manual`, or a type outside `dispatch_repos.SERVED_TYPES`
  parks the card at `idle`/`failed` with `awaiting_action` plus a comms
  reason; `GET /queue` reports those separately under `human_waiting`
  (`kind: human|unserved`, `owner`, `next_action`) instead of mixing them
  into claimable `queued` (KNB-0013).
- **`/action do:queue|retry|close|hold` — verify-or-loud** (card
  `board-api-queue-write-verify-lost-race-f85f2f`, 2026-11-24): the
  response no longer fires on write-and-hope. After the flock releases,
  board-api flushes the queued commit (bounded
  `BOARD_API_ACTION_VERIFY_S`, default 8s), re-reads the card, and
  compares a fingerprint of the mutated fields (`column`,
  `awaiting_action`, `action`, `claim.session`) against both the
  written state and the pre-write state. Written-state + porcelain-clean
  → `200 {"verified": true}`. Pre-write state → an autostash pop (or
  equivalent) already reverted the write: the verb is re-applied once
  under the flock and re-verified (response notes
  `write re-applied after pull race`). Anything else — still dirty, a
  concurrent writer's third state, a failed re-read — answers `503`
  with `verified:false` so the caller retries instead of believing a
  `queued` that isn't there. `BOARD_API_ACTION_VERIFY_S=0` restores the
  old fire-and-forget. Belt-and-suspenders on the git side:
  `git-safe-pull.sh` now preserves the stash side (stage 3) of card
  autostash-pop conflicts as `<card>.local-conflict-<ts>` before
  resolving upstream-wins, and `reconcile-local-conflicts.py` folds it
  back — modify/modify card conflicts still union-merge inline via the
  card-union driver; the sidecar covers modify/delete and driver
  failures. Ops note: a `503` from `/action` means "mutation may or may
  not have landed — retry"; `queue`/`retry` are idempotent so a retry
  converges (`already queued` verifies trivially).
- **`/attach`** — card file/photo evidence
  (`board-attachments-photo-image-evidence`, 2026-11-17). `payload` is
  base64 (a `data:` URI prefix is stripped); `filename` is sanitized to
  `[A-Za-z0-9._-]` and must end in an image/pdf/video/text/archive
  extension — anything servable as an executable content-type
  (html/svg/js) is refused. The file lands at
  `docs/ssot/kanban/attachments/<card-id>/<name>` — inside the repo, so
  it commits and propagates like card YAML (same flock, one commit with
  the card) — and a comms entry links it:
  `attachment: <repo-path> — <name> (N B)`. Collisions suffix `-2`/`-3`
  unless the bytes are identical (idempotent re-post). Cap
  `BOARD_API_ATTACH_MAX_BYTES` (12 MiB decoded). The board UI can't see
  that tree — `/srv/public` is all the web container mounts — so every
  `render-board2.py` run mirrors it into
  `stacks/web/public/apps/board2/attachments/` (gitignored), where
  Caddy's file_server exposes `attachments/<id>/<file>`; board2 renders
  a 📎 count badge on the tile, an Attachments thumbnail strip in the
  card modal, and inline thumbs under any comms entry that carries a
  repo path.
- **`/job`** — `status` ∈ `queued|claimed|running|done|failed|stalled|
  cancelled`; `comms`/`note` appends `{at,from,text}` to a JSON log in
  `meta.comms` (cap 200); `parent` accepts a post id or a sibling job slug
  (job trees). `from` accepts actors or daemon/host names (`queue-mgr`,
  `tony-dell`). queue-mgr (`scripts/ops/queue-mgr.py`, tony-dell
  `queue-mgr.timer` 5m) mirrors `gdrive:ada-nest` queue/packs state
  through this — Colab workers and watchers never write.
  **Lifecycle contract (OPS-0923):** status changes follow
  `JOB_TRANSITIONS` — terminal `done`/`cancelled` exit only via
  `queued`/`failed`, and `done` requires `result_ref` plus verified
  artifact evidence (`evidence[]`, `verified:true`, or
  `confidence=verified`); violations are HTTP 400 before any WP write.
  `meta.status` is an alternate carrier for the same field — it is
  folded into the gated status (a top-level/meta disagreement is a
  400), so it cannot bypass the contract. queue-mgr sends the pack
  `done` marker as `evidence[]` on every done write.
  Accepted evidence persists to `meta.evidence` +
  `meta.artifact_verified`. Read side: `GET /nest-jobs?slug=&limit=
  &comms=1` lists the mirror for reconciliation
  (`scripts/ops/nest-job-reconcile.py`).
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
- **`/wiki/page`** — the escape hatch for support pages the kind-gated
  sinks can't reach (portal/index/host pages, the Education/Report
  templates). `WIKI_PAGE_PREFIXES` in board-api allowlists
  `Education:`/`Reports:`/`Infrastructure:` titles plus the configured
  template names; everything else (main space, `News/`, `PrivateNews:`,
  other namespaces) is refused so this can't become a backdoor around
  the News review gate. Prefixed titles additionally verify via siteinfo
  that the namespace is really registered — an unregistered prefix is
  rejected instead of littering main space. `Infrastructure:` (ns 3000)
  was added 2026-11-20 (card `wiki-page-door-infrastructure-namespace`)
  for host pages like `Infrastructure:Hosts/tony-dell/Backup-and-Recovery`;
  it's Lockdown-protected, so the write only succeeds because the door's
  wiki account sits in the inhouse/sysop group — the allowlist is a
  guard, not an ACL grant.
- **`/wiki/extension`** — the controlled extension-management door
  (card `wiki-extension-control-plane`). `action` is
  `list|install|enable|disable`; `list` needs no confirm and returns
  the siteinfo extension table plus the approved-name allowlist
  (CategoryTree, Mermaid, MsUpload, MultimediaViewer, Cargo, PageForms,
  Lockdown — Graph/Drawio/arbitrary repos are refused). One extension
  per call; mutations require `confirm:true` (400 otherwise — list
  first, then confirm). Springboard stays server-side: callers never
  pass repo/branch/commit/delete parameters. Each mutation captures
  Special:Version + the extension table before/after, verifies the
  change is reflected, and writes a receipt to
  `~/.local/state/board-api-wiki-ext/` on the service host
  (`BOARD_API_WIKI_EXT_STATE` overrides). Mutations are idempotent:
  when the extension is already in the requested state (present for
  install/enable, absent for disable — siteinfo lists enabled
  extensions only) the door verifies the end-state and returns
  `verified:true, no_op:true` with a receipt without calling
  Springboard. Otherwise Springboard errors or an unverified result
  surface as 502 — the door never claims an install that didn't
  happen. Wiki credentials stay in
  `~/.config/secrets/wiki-h3-gizmo.env` on idc03; agents (Ada voice,
  ada-ocb `ada_wiki_extension(s)`, OpenCode) reach it only through this
  endpoint.

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
`tg_thread_id`, `qc`, `sha256`, …).

Telegram delivery stays private-first and concise: `TelegramSink` sends
the rendered text plus `project_id`/`card_ref`/`job_ref` to the DevNest
relay unless `meta.tg_thread_id` explicitly pins a thread. The relay
resolves those refs through its project topic registry (manifest-backed),
so bound project events land in the project forum topic instead of
General; explicit project/card refs with no active binding are refused,
while unmatched non-project job refs keep the legacy General behavior.
A refused delivery retries via the outbox then dead-letters — the fix is
a binding, not a resend: create a `PRJ <project-id> — <title>` forum
topic in DevNestHA and a
`~/.local/share/devnest/projects/<id>/project.json` manifest with a
`topic{thread_id,…}` block (the relay reconciles it into topics.json);
card-scoped chaba-board lifecycle events carry `project:"chaba"` and
land in the `PRJ chaba — board ops` topic (OPS-1386, thread 100).
Artifact-style events should put Drive/file refs in `media[]` or
`evidence[]` and QC/hash details in `meta` — the Telegram renderer shows
short refs/metadata, never source binaries.

**Kind → sinks (defaults):**

| kind | sinks | note |
|---|---|---|
| progress | `job`, `board` | heartbeat-class: throttled, never TG |
| milestone | `job`, `board`, `telegram` | |
| report | `report`, `board` | dossier needs `project` slug |
| lesson | `lesson` | Education CPT |
| news | `news`, `board`, `telegram` | evidence required |
| alert | `telegram`, `board`, `job` | |

**Job-sink contract (OPS-0923):** the `job` sink fires only for events
with an explicit `job` ref — card/project-scoped events audit via the
`board` sink and never mint `nest_job` posts. Status is never implied
by kind beyond liveness hints: `progress`→`running`, `alert`→`stalled`,
`milestone`→no status change (a milestone is a checkpoint, NOT
terminal evidence). `meta.job_status` is the explicit override; any
`done` assertion hits the same `result_ref` + verified-evidence gate
as `/job` — a rejection is a per-sink `skipped` receipt
(`job status rejected: …`), never outbox-retried, while sibling sinks
still deliver. `evidence[]` and `confidence=verified` pass through to
the job write (`result_ref` defaults to `evidence[0]`).

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
