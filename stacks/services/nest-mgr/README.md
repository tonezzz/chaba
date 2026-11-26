# nest-mgr — per-host Nest manager (observer-governor + gated actuation v2)

Cards: `nest-manager-node` (v1), `nest-mgr-v2-actuation` (v2 actuation
plane). One `nest-mgr.service` per host; deployed fleet is
**idc02, idc03, con01, mn01, tony-omen, tony-macbook** (tony-dell retired
to omen in the 2026-10-19/20 phase-5 LAN migration; tony-macbook
installed 2026-11-17 via card ops-macbook-nestmgr-install / SYS-0158).

A *governor mind* for the host's Nest fleet (the Asher pattern from
`docs/kb/nest-asher-polity-inspiration.md`): it discovers every nest node
on the host, adopts the ownerless ones, and publishes a live
`nest-<host>` CMS page that auto-surfaces on the `/chaba-nest` dashboard.

**v2 adds a bounded actuation plane** — monitor → recommend → guarded.
The observer behavior is unchanged; actuation only ever runs
allowlisted actions under circuit breakers, and every recommendation and
action lands in the `actions[]` audit ring + the CMS page.

## Discovery

A nest node is any of:

- a systemd **user unit** matching `jev|student|bankq|nest|serve-*.py|openjev`
  (unit name, Description, or ExecStart — covers quadlet-generated units
  like `openjev-student.service`)
- a **`serves:`/`lanes:`** entry in `~/CascadeProjects/ada-voice/tests/bench/topologies.yml`
  whose host resolves here (hostname, `*.taila0626a.ts.net`, tailnet IP,
  or loopback)
- a live **`/metrics`** endpoint on a known nest port (fixed list — no
  port scan)

Nodes found under multiple sources merge on their endpoint port.

## Ownership

- `NEST_OWNER=<x>` in the unit's `Environment=` (or unit file/drop-ins)
  → owner `<x>`; `NEST_OWNER=none` opts out → shown `unmanaged`
- a kanban card listing the node under `nest_nodes:` (or `nest_node:`)
  → owner `card:<id>`
- everything else → **ownerless → adopted** (`owner: manager`), tracked
  in `~/.local/share/nest/manager-state.json`

## Report

`ada-cms-pages/nest-<host>` via the MDDB `add` write path (same as
report-distill). One table row per node: name · kind
(student/scorer/lane/brain/ops) · endpoint · state
(active|shadow|failed|parked) · goal (topology task/card) · progress
(requests/escalations/uptime from `/metrics`, last bench) · owner.
An **Actuation** section shows the mode, flags, lifetime counters, and
the recent audit rows.

Cadence: 15 min, plus immediately on state change (including new
actuation events), plus when the page's `ada-cms-automation` registry
doc sets `run_now` (the CMS regenerate button queues it; this daemon
clears it — no allowlisted command needed).

## Actuation modes (v2)

Resolved every tick; flags can only **lower** the mode, never raise it:

| mode | behavior |
|---|---|
| `monitor` | v1 — detect + report only (default) |
| `recommend` | plans allowlisted actions, logs to `actions[]` + CMS, **executes nothing** |
| `guarded` | additionally executes allowlisted restarts — requires `actuation.on` opt-in |

Mode is set by env `NEST_MGR_MODE` (unit drop-in wins) else
`~/.local/share/nest/mode` else `monitor`.

Flag files under `~/.local/share/nest/`:

- `actuation.off` — **kill switch**, presence forces monitor (checked
  every tick; `rm` to clear)
- `actuation.on` — per-host opt-in required for guarded to execute
- `mode` — `monitor`|`recommend`|`guarded`
- `host-circuit.open` — host breaker tripped (>5 executed restarts/hour);
  `rm` to reset
- `manual-units` — units an operator holds, one per line — never restarted
- `restart-allowlist` — restart-eligible units, one per line
- `circuit/<unit>.open` — per-unit breaker (2 failed restarts/hour);
  `rm` to reset

## Guarded auto-restart policy

A unit restarts only when **all** hold:

- `state == failed` on **3+ consecutive ticks** (60 s tick → ~3 min)
- allowlisted: `NEST_RESTART_OK=1` in the unit env/file/drop-ins, **or**
  listed in `restart-allowlist`
- cooldown 5 min since last attempt; **≤2 restarts/hour/unit**
- never-list clean: not card-owned (`nest_nodes:`), not
  `NEST_OWNER=none/unmanaged`, not `nest-mgr` itself, not in
  `manual-units`, not a topology `prod` lane (`NEST_MGR_PROD_OK=1`
  overrides), not `Restart=on-success`, no open unit circuit
- host budget: ≤5 executed restarts/hour or the host circuit opens

Every event — recommended, held (with the blocking gate), executed,
circuit-open — appends `{ts, host, unit, prior_state, action, reason,
outcome}` to `manager-state.json` `actions[]` (ring, last 200), renders
on the CMS page, and rides to HA via device-telemetry `svc_nest_mgr_*`
sensors (`mode`, `act_1h`, `circuit`, `last`).

Audit tail: `nest-mgr.py --actions`.

## Install / verify

```bash
./install.sh                     # whole deployed fleet (monitor mode)
./install.sh idc02 con01 mn01    # pilot hosts only
./verify.sh                      # unit + state + CMS page per host
python3 test-actuation.py        # gate-matrix test (tempdir-isolated, no systemd)
```

Upgrading a v1 host to v2 lands in **monitor** — v1 behavior plus the
actuation bookkeeping block, zero behavior change. Phase-0 rollout:

```bash
ssh idc02 'echo recommend > ~/.local/share/nest/mode'   # recommend on
ssh idc02 'touch ~/.local/share/nest/actuation.off'     # panic stop
ssh idc02 'rm ~/.local/share/nest/actuation.off'        # clear
```

State + script live under `~/.local/share/nest/` on each host
(self-contained — no repo checkout required at runtime beyond the
topologies/cards inputs).

## Files

- `nest-mgr.py` — the manager (stdlib + pyyaml only)
- `nest-mgr.service` — user unit (`ExecStart=...nest-mgr.py --loop`)
- `install.sh` / `verify.sh`

Manual ops on a host:

```bash
python3 ~/.local/share/nest/nest-mgr.py --discover   # list nodes
python3 ~/.local/share/nest/nest-mgr.py --once       # state + publish now
python3 ~/.local/share/nest/nest-mgr.py --report     # render, no writes
python3 ~/.local/share/nest/nest-mgr.py --actions    # audit tail
```
