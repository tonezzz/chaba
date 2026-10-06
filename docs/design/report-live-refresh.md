# Report live-refresh graph — design

**Status:** decisions recorded (§8) — ready to schedule P1
**Ask (2026-10-06, Tony):** make reports live-refreshable in 3 layers —
(1) Ada/reader gets the current summary immediately, (2) the top report
triggers downward invalidation to catch what changed since it last ran,
(3) leaf reports regenerate live and push the update up the chain to the
initiator, which then fans it out to every other report linked to that
piece of info. Plus: an update-pending list per page.

**Context:** today the chain is a single scheduled oneshot
(`chaba-system-report.service`, 06:45) that runs L1 audits → L2 rollup →
L3 overview top-down, and readers (`/apps/system-report/`, CMS page
`system-report`, Ada's `cms_read`) see the snapshot until the next run.
`report-api` (added 2026-10-06) can trigger the whole chain on demand —
this design turns that blunt trigger into per-node, dependency-aware
refresh with pending lists and sideways propagation.

## 1. The model — a graph, not a chain

Every report node already exists in `ssot.reports.yml` with `id`,
`layer`, `meta`, `cadence`, `output`, `generator` — and **`children`:
the declared input edges** (fleet lists its audit-hosts, system-report
its L2s, daily-brief its producers). The graph reuses that field; no
new edge type:

- `children` = "what this render consumes" — downward walk for
  invalidation, reverse index gives sideways fan-out (a leaf may be a
  child of several parents).
- Leaf reports (single-camera report, per-service report, host audit)
  are all just nodes — the graph doesn't care about layers, only edges.

## 2. State — meta + pending list

Extend `meta.<node>.yml` (the schema already exists; additions are
backward-compatible):

```yaml
node: camwall-daily
generated_at: '2026-10-06T11:26:36+07:00'
status: ok
inputs_at:                        # NEW — what this render consumed
  camwall-snapshots: '2026-10-06T06:45:02+07:00'
pending:                          # NEW — the per-page update list
  - requested_at: '2026-10-06T12:00:11+07:00'
    by: ada                         # ada|web|timer|manual
    reason: user-refresh            # user-refresh|input-dirty|linked
    depth: up                       # up = caller wants me+ancestors fresh
```

**The pending list per page is just `meta.<node>.pending[]`.** Any
reader (page, Ada, another node) can show "2 updates pending" without a
central queue — and the queue survives restarts because it's YAML on
disk, like everything else here.

A derived `reports/pending-index.yml` (rebuilt on read, not stored
state) gives the coordinator a flat view: node → pending entries →
which inputs are dirty.

## 3. The three-layer flow

### Layer A — serve now, refresh behind (initiator-facing)

`POST /apps/system-report/api/refresh {node, depth}` — or Ada's tool —
does:

1. Mark `node.pending += {by, reason: user-refresh}` and return
   immediately with the **current** summary + `freshness` (age,
   pending count).
2. Hand off to the coordinator (below). Never block the caller on the
   chain — a full refresh is minutes.

So Ada answers *"As of 06:45: all green except X — I'm pulling live
numbers now"* — correct immediately, better shortly after.

### Layer B — downward invalidation (catch what was missed)

The coordinator walks `informs`-reversed edges from the target node to
the leaves:

- A node is **dirty** when any `inputs_at[child] < child.generated_at`
  (the child changed after I last consumed it), when the child's meta
  is absent, or when the child itself has pending entries.
- Dirty leaves get `pending += {reason: input-dirty}` and are queued to
  run; clean leaves are skipped — this is the "only update what changed"
  property.
- Cap: `max_depth`, `max_nodes`, and a per-subgraph lock so two
  overlapping refreshes coalesce instead of duplicating work.

### Layer C — upward + sideways propagation

When a leaf finishes:

1. Write its meta with new `generated_at`/`content_hash`.
2. For every node `n` where `leaf ∈ n.inputs`: mark `n` input-dirty →
   `pending += {reason: input-dirty}` → queue `n` to re-run once *all*
   its inputs are fresh.
3. Sideways: every `informs` target of the leaf — including CMS pages and
   reports other than the initiator's branch — is queued the same way.
   One camera report update refreshes `fleet`, `daily-brief`, and the
   camwall CMS page in one pass.
4. When the initiator node itself re-runs, emit the completion notice
   (next section).

Ordering falls out of the pending marks: a node only runs when it has a
pending entry **and** no dirty inputs — no central scheduler needed
beyond a small work queue.

## 4. Coordinator — `report-graph` runner

Extend `report-api` with a single in-process worker (tony-dell,
127.0.0.1:8792):

- `POST /refresh {node="system-report", depth="subtree"}` → 202 +
  `{pending_id}`; starts the walk.
- `GET /status` → per-node running/pending/last_generated (what the web
  button already polls).
- Executors: leaf generators run as `subprocess` with per-node
  `flock` (`/tmp/report-graph-<node>.lock`) — a running leaf can't
  double-run; a second request just merges pending entries.
- Timeouts per generator (default `TimeoutStartSec` parity); failure →
  node `status: error`, pending entry resolved with `error`, parents
  keep last-known-good content and show the delta.

## 5. Notifying the initiator (and Ada)

When the requested node's regeneration lands:

- **Web**: the button already polls `/status` → shows fresh data.
- **Ada**: write an `ada-ha-events-{instance}` doc
  (`kind: report-updated`, `node`, `delta-summary`) — her existing ops
  event path surfaces it on the next turn, and she can say *"the report
  finished — here's what changed."* No new channel needed.
- **CMS**: nodes with `informs` to a CMS page republish it
  (`publish_cms_page` path already exists in `report-system.py`).

## 6. Safety & semantics

- **Coalesce**: N refreshes on overlapping subgraphs → one walk; pending
  entries merge (idempotent by {node, reason}).
- **Budget**: `depth: leaf` (just this node), `subtree` (default — dirty
  inputs + ancestors), `full` (everything it informs, recursively).
  `full` is never auto and is rate-limited (§8.1 cost standard).
- **Failure isolation**: a dead leaf marks error + parents render with
  last-known values and a `delta` flag — absence is loud, never silent.
- **No partial reads**: generators write to tmp + rename; readers never
  see half-written content.
- **Timer unchanged**: the 06:45 chain stays as the daily full sweep;
  live refresh handles gaps between runs.

## 7. Phases

| Phase | Scope | Deliverable |
|---|---|---|
| P1 | edges + coordinator | `informs`/`generator` in ssot.reports.yml, `pending`+`inputs_at` in meta schema, `report-api` grows `/refresh {node}` subtree walk (down-dirty, run leaves, walk up) |
| P2 | pending lists + sideways | pending-index view, linked/CMS fan-out, "pending" badge on the monitor page |
| P3 | Ada | `report_refresh` tool (answer-now + background refresh), `report-updated` events into `ada-ha-events-*`, freshness phrasing |

## 8. Decisions (2026-10-06, Tony)

### 8.1 Depth — "if it's not a big job, just do it in the background"

So the standard needs a measurable definition of "big". Proposed —
a node is **light** when all hold:

- `timeout` ≤ 2 min (or no declared timeout — measured once, then set)
- no remote SSH in its generator (no cross-host fan-out)
- no paid/external API calls (embeddings, LLM, cloud APIs)

A refresh request **auto-runs in background** when the whole dirty
subgraph is light and ≤ 5 nodes. Anything bigger: the initiator gets
the cached answer + `pending` marked, and the reply says the scope
("refresh queued — it touches 12 nodes including 3 host audits").
Ada never blocks on either path; the difference is whether she says
"refreshing now" vs "queued — it's a big one". `depth=full` (sideways
fan-out across the whole graph) is never auto — web button or explicit
"refresh everything" only.

### 8.2 Generators — declared, executed through a standard runner

Suggestion: **both**. Keep `generator:` explicit per node (the odd
ones — SSH audits, HA pulls, CMS publishers — shouldn't be derived by
convention), but add one executor `scripts/report/run-node.py <id>`
that all refresh paths call: it reads the registry, applies the
per-node lock + timeout + cwd, runs the generator, writes meta
(`generated_at`, `inputs_at`, clears the consumed `pending` entries).
So generators stay *declared*; *how they run* is standardized. New
leaves only need `generator` + `informs` in the registry — no runner
plumbing per report.

### 8.3 Pending expiry — explained

`pending[]` is a promise: "someone asked for fresh data, it's coming."
If a leaf keeps failing (cam offline, host down, generator crash), that
entry would sit forever — the page says "updating" permanently and the
promise is silently broken. Expiry fixes that: after **3 failed
attempts or 24h** (whichever first), the entry is resolved as
`failed`, the node goes `status: error`, and one `report-updated`
event notes the failure — so Ada/the page can say *"the camera report
is broken, last good data was 06:45"* instead of hanging. Same
principle as the rest of the system: absence is loud, never silent.
