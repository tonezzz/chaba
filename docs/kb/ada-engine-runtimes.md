# Per-engine runtimes — parallel ada engine versions on idc03

Card `ada-engine-runtimes` (ref ADA-0155, gap from `ssot.apps.ada-engines.yml`).

## Problem

Every `ada-*` lane on idc03 runs the same `~/CascadeProjects/ada-voice`
checkout + `.venv` (see the shared-fate vector in `ha-ada-isolation.md`).
Fleet-wide the engine version is therefore single: `deploy-ada.sh` moves
all lanes together, and two lanes can never run different engine builds
at once. The engine-lines model (`ssot.apps.ada-engines.yml`) needs lanes
to bind different `<line>-<version>` engines simultaneously — e.g. ada-1
on production lanes while ada-2 soaks on a dev lane.

## Decision: checkout+venv runtime slots (quadlet deferred)

**Chosen:** one runtime dir per engine —
`~/CascadeProjects/ada-engines/<engine-id>/` holding a pinned ada-voice
checkout + its own `.venv`. Binding a lane to an engine is a systemd
drop-in that repoints the lane unit's `WorkingDirectory`/`ExecStart` at
the runtime. This is the smallest change that satisfies the contract:
lanes, ports, env files, keys, banks, and relay pointers are untouched —
only the code the unit executes changes.

**Deferred:** a quadlet/podman image per engine (host-hygiene R5 shape).
It buys stronger isolation and reproducible builds, but ada-voice is not
containerized today (uvicorn + Gemini Live websockets + local tool
scripts + venv deps), so image-ifying is its own project. The binding
model below is engine-source-agnostic: a quadlet slot can later replace
the checkout dir without touching lane units or the contract — the
drop-in just points `ExecStart` at `podman run ...` instead of a venv
python. Revisit when ada-2 needs hard isolation from the host.

## Layout

```
~/CascadeProjects/ada-voice/                  # ada-1 — the shared default
~/CascadeProjects/ada-engines/ada-2.0/        # engine runtime (checkout + .venv)
~/.config/systemd/user/ada-kk-dev.service.d/engine-ada-2.0.conf   # binding drop-in
~/.config/systemd/user/<unit>.service.d/isolation.conf            # existing caps (unchanged)
~/.config/systemd/user/<unit>.service.d/stagger.conf              # existing stagger (unchanged)
```

- Engine id = `<line>-<version>` from the engines SSOT (e.g. `ada-2.0`,
  `chaba-ops-0.1`, `edge-0.1`). The dir name IS the engine id — no
  mapping table to drift.
- A runtime is **code only**. Lane identity (env file, caller keys,
  `ADA_INSTANCE_ID`, banks, persona instructions, port) stays with the
  lane. Two engines never share a runtime dir; two lanes may share one
  engine runtime (that's the normal case — all ada-1 lanes share
  `~/CascadeProjects/ada-voice` today, which is runtime `ada-1.x`
  implicitly).
- `ada-1.x` has no runtime dir — the legacy shared checkout IS its
  runtime. New engines always get `ada-engines/<id>`.

## Binding mechanics

Lane → engine binding is per-unit config, not code:

1. `engine-runtime.sh bind <unit> <engine-id>` writes
   `~/.config/systemd/user/<unit>.service.d/engine-<engine-id>.conf`:
   - `WorkingDirectory=` → runtime checkout
   - `ExecStart=` (reset) → runtime `.venv/bin/python` + the same
     entrypoint args the unit already used (path-substituted, so
     `pwa_server.py`, uvicorn flags, `--app-dir` etc. carry over)
   - `ExecStartPre`/`ExecStartPost` are left alone unless they embed the
     old checkout path (the stagger hook doesn't — it only sleeps).
2. `daemon-reload` + `restart <unit>`; verify `curl
   http://127.0.0.1:<port>/api/health`.
3. `unbind <unit>` removes the drop-in → lane falls back to the shared
   ada-1 checkout. Instant, reversible — same shape as the relay pointer
   flips in `persona-eval-ab.md`.

Bindings key on **lane unit**, never on engine internals — matching the
grand-rename rule (lane ids are the stable contract keys; unit names are
mid-rename).

## Cgroup caps / hygiene

- Existing lane units already carry `isolation.conf`
  (`MemoryMax=2G`, `CPUQuota=150%`) and `stagger.conf` — binding does not
  touch them; drop-ins compose.
- A **new test lane** for a variant engine (the `persona-eval-ab.md` §2
  flow: copy env, new `ADA_INSTANCE_ID`, free port) needs both drop-ins
  at creation. `engine-runtime.sh lane <engine-id> <lane-id> <port>`
  scaffolds env copy + unit + isolation + stagger in one step.
- Every runtime dir and unit must be declared: stack `state:` line in
  `stacks/idc03/<lane>/stack.yml` for the lane, and the engine runtime
  recorded in `ssot.apps.ada-engines.yml` `engine_registry` + this doc.
  `scripts/audit-hosts.py --host idc03` is the enforcement.

## Secrets

Runtime dirs hold **no secrets**. Lane env files
(`~/.config/secrets/ada-<lane>.env`) are unchanged by binding — the
engine reads whatever the lane gives it. Engine-level config that must
differ per build (e.g. a different provider key for ada-2 experiments)
goes in the lane env or a runtime-local `.env` the engine explicitly
supports — never inline in units (host-hygiene R4).

## Procedure — stand up ada-2 and bind a dev lane

```bash
# on idc03
scripts/ada/engine-runtime.sh provision ada-2.0 --ref <git-ref-or-branch>
scripts/ada/engine-runtime.sh lane ada-2.0 ada-kk-dev-ada2 8011   # test lane
#   -> copies ada-kk-dev.env to ada-kk-dev-ada2.env, writes unit + caps
scripts/ada/engine-runtime.sh bind ada-kk-dev-ada2 ada-2.0
systemctl --user daemon-reload && systemctl --user restart ada-kk-dev-ada2
curl -sf http://127.0.0.1:8011/api/health
# contract suite + scenario pack (ada-engine-contract-suite) against :8011
# soak, then either bind a real lane or keep as the permanent ada-2 dev twin
```

Rollback at every step: `unbind` (drop-in removal) or `systemctl --user
stop` the test lane. The shared ada-1 fleet is never touched by
provisioning a new engine — runtimes are additive.

## What this does NOT do

- Does not change `deploy-ada.sh`: it still deploys ada-1 to the shared
  checkout. Engine runtimes are pinned refs; upgrading an engine =
  `provision` a new `<line>-<version>` dir (or `git -C <dir> fetch +
  checkout` for a minor bump) + rebind — deliberately outside the
  fleet-wide deploy path so a bad ada-2 build can't canary-kill ada-1.
- Does not implement per-caller engine pinning — that's
  `persona-ab-split-routing-relay` (relay-side `LINE_CALLER_BACKENDS`),
  orthogonal to which code a lane's unit executes.
- Does not containerize ada-voice (see Decision).
