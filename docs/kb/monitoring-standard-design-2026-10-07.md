# Monitoring Standard — assessment & design (2026-10-07)

Driver: Tony — "we've missed detection of a lot of issues; I need an
ever-evolving monitoring structure & report that tells me what's going
on and what needs my attention."

## 1. What exists today

| Asset | What it does | Where output lands | Who reads it |
|---|---|---|---|
| `ssot.health.*` (17 files, ~149 checks) | declares http/systemd/tcp checks, `expected_state` incl. `inactive` | consumed by mcp-health | — |
| `mcp-health` server.js | executes checks, keeps sqlite history | MCP tool responses | whoever asks |
| `service_criticality` map | critical/important/optional tiers | ~15 services tagged | inbox drafts |
| `mcp-health-to-inbox.py` | health status → focus-inbox drafts | focus-inbox | flooded queue |
| `/apps/health-check` CMS | health dashboard page | CMS | manual visit |
| `ops-digest.py` (new) | ada-ops events → 08:00 telegram | telegram | Tony daily |
| ada-ops events (`ada-ha-events-tony`) | tool storms, strips, drift | mddb | digest + report feed |
| `gh-runs-watch` | CI failures → inbox | focus-inbox | triage |
| `ssh-canary` | connectivity canary → events | focus-inbox/events | recovered msgs |
| render-memory `infra-digest` | ada-ops + spend + ha-events + tasks | memory context | Devin sessions |
| systemd leash/watchdog units | self-healing reapers | journal | silent |

## 2. Why we miss things — incident taxonomy

| Miss | Root cause class |
|---|---|
| jev-student crash-looped ×4290 on idc01 | **No check declared** + nothing counts restart counters |
| OR key rotated → 401s on openclaw | **No auth-validity check** on stored provider keys |
| mddb wedged at 16.4GB RSS | check exists, but probe dying = report unread → **no escalation** |
| ONB dead overnight | check existed; **nobody consumed the signal** |
| open-jev 3.6 CPU-h/day | **no resource-burn / expected-inactive check** (now fixed) |
| /tmp/bltest tmpfs artifact | **coverage gap** — stray test infra invisible |
| digest agent failing days | **no self-check** on the monitor itself |

Four failure modes: (a) no check exists, (b) check exists but result
lands where nobody looks, (c) check exists but nothing escalates,
(d) the monitor itself fails silently. Today's setup loses to (a)+(b).

## 3. The standard — five layers

```
DECLARE      ssot.health.*  + coverage lint (CI)
   │         every status:running service needs a check or a
   │         declared no_health: reason — this is the "ever-evolve" hook
EXECUTE      mcp-health runner + timers + probes
   │         every run stamps last_run_ts (self-check substrate)
AGGREGATE    ops-state.yml  — single merged artifact:
   │         health results + ada-ops flagged + dispatch jobs
   │         + canary + CI watch + probe staleness
REPORT       /apps/ops-health CMS page + extended morning digest
ESCALATE     critical → telegram now; action-needed → kanban request
```

### Severity model (extend existing map)

- **critical** — Ada-facing path down, auth broken, crash-loop,
  data-loss risk → immediate telegram (`openclaw message send`)
- **warn** — degraded/flapping/drift/unexpected-active → morning digest
- **info** — point-in-time noise → report page only

`expected_state: inactive` is a first-class check type (dormant-by-design
services — JEV scorers, standby relays) — unexpected uptime = warn.

### Coverage lint (the evolving part)

CI step: `services(running) − health_checks − no_health:` must be empty.
New service lands → warning until it gets a check or an exemption.
Also lints: every criticality service has a check; every check's host
exists in inventory; probe staleness (a check with no run in 48h
flags itself).

### The attention report (what Tony reads)

```
OPS HEALTH — 2026-10-07 14:05 (+07)

▸ ACT NOW     crash-loop jev-x (restart 4,290); OR key 401 on openclaw
▸ WATCH       open-jev up 3h outside bench; mddb RSS 11GB (cap 14GB)
▸ DIGEST      24h: 12 ops events, 3 flagged · tasks overdue 13
▸ QUIET       143/149 checks green; 4 dormant correctly idle
▸ SELF        probes: all fresh; mcp-health last run 4min ago
```

Rule: the report leads with *actions*, not statuses. If ACT NOW is
empty, the rest is skim-only.

### Escalation paths

| Severity | Path |
|---|---|
| critical | `openclaw message send --channel telegram --to 8960073266` now |
| warn | into morning `ops-digest` (extend: merge health anomalies) |
| action-needed | kanban card `requests:` entry (existing mechanism) |

## 4. Build-out phases

- **P0 (cheap, this week)** — coverage lint script + declare
  `no_health:` on intentional gaps; extend `ops-digest.py` to merge
  mcp-health error/unknown states + service uptime anomalies into the
  08:00 report; add probe-staleness self-check line.
- **P1** — `ops-state.yml` aggregator job (hourly, merges all signal
  sources); `/apps/ops-health` page from it (CMS layout standard);
  critical→telegram escalation via openclaw send.
- **P2** — restart-counter check (systemd NRestarts > threshold);
  auth-validity probes for stored keys (OR, telegram, google);
  resource-burn checks (CPU-h/day, RSS ceilings) as a check type.
- **P3** — kanban auto-request for persistent warns (≥3 days).

## 5. What NOT to change

- keep focus-inbox as the alert *queue* — aggregation feeds it, doesn't
  replace it
- keep ada-ops events as the Ada-side signal; this standard is the
  host/service side
- monitoring must stay zero-LLM for detection (digest taught us: free
  models fumble schemas) — LLM only ever *summarizes* an already-
  assembled report
