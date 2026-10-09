# nest-mgr — per-host Nest manager (observer-governor v1)

Card: `nest-manager-node`. One `nest-mgr.service` per host; the starting
set is **idc03, tony-omen, tony-dell**.

A *governor mind* for the host's Nest fleet (the Asher pattern from
`docs/kb/nest-asher-polity-inspiration.md`): it discovers every nest node
on the host, adopts the ownerless ones, and publishes a live
`nest-<host>` CMS page that auto-surfaces on the `/chaba-nest` dashboard.

**v1 is strictly observational** — reports and health-checks only, never
restarts or enforces (leash principle, `ssot.nest-training.yml`
`promotion_gate`).

## Discovery

A nest node is any of:

- a systemd **user unit** matching `jev|student|bankq|nest|serve-*.py|openjev`
  (unit name, Description, or ExecStart — covers quadlet-generated units
  like `openjev-student.service`)
- a **`serves:`/`lanes:`** entry in `~/CascadeProjects/ada-pi/tests/bench/topologies.yml`
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

Cadence: 15 min, plus immediately on state change, plus when the page's
`ada-cms-automation` registry doc sets `run_now` (the CMS regenerate
button queues it; this daemon clears it — no allowlisted command needed).

## Install / verify

```bash
./install.sh                 # all three hosts
./install.sh idc03           # one host
./verify.sh                  # unit + state + CMS page per host
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
```
