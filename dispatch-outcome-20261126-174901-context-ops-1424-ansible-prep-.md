# Dispatch outcome — ansible-ada-ocb-tony-dell-fallback (OPS-1424 follow-up)

## What was found

**tony-dell ocb_pane fallback is healthy — the failure was a playbook bug, not host drift.**

Read-only diagnosis over BatchMode SSH from con01:

- Probe prerequisites all present: python3 3.14.4, `~/.local/node24` npm/node, `@openchamber/web` pkg dir.
- Live pane state: `openchamber.service` active, `openchamber-update.timer` active, `ada-ocb-bridge-sync.timer` active (`ada-ocb-smoke.timer` inactive — idc02-only unit, correctly not required), bind `127.0.0.1:3000`, `local_http=200`, `startup.env` mode 600, litellm dropin present.
- Drift vs pins: web 2.8.0 (= pin), cli 2.4.1 (pin 2.4.2), `models.status` patch absent. All three are already exempted for `role=fallback` (`ocb_strict_roles: [primary]`) — reported, not fatal.

**Root cause of the noisy recap:** the localhost assert/report phase in `ada-ocb-verify.yml` / `ada-ocb-preflight.yml` iterates the full `ocb_pane` group regardless of `--limit` or probe success. When the probe play skipped tony-dell (`--limit idc02,localhost`, or an unreachable host), `hostvars['tony-dell'].ocb_probe` was undefined → the assert templated `Undefined` (crash) and the report builder emitted all-`?` checks scored `fail` (see `reports/ansible-benchmark/ada-ocb-verify/20261126T090125Z/tony-dell.yml` on the controller).

**Decision:** keep tony-dell declared fallback/non-strict — do NOT align it to the 2.8.0/2.4.2+patch contract. That contract gates the primary; the fallback is a pre-migration soak copy pending Tony's retire decision. Aligning would be a host mutation requiring same-session approval anyway — out of scope, none performed.

## What changed (worktree only, uncommitted)

- `ansible/playbooks/tasks/ada-ocb-probe.yml` — probe tasks `ignore_unreachable`; no-JSON probe now yields `ocb_probe={error: ...}` (audit-log-shipper pattern) instead of a host-fatal assert. Unreachable/limit-excluded hosts simply get no fact.
- `ansible/playbooks/tasks/ada-ocb-assert.yml` — producer contract runs only on hosts with a usable `ocb_probe` (`is defined` + no `.error`), `p.get()` throughout; new assert fails loudly if a **strict-role** host produced no probe; non-strict unprobed hosts get an INFO line, not a crash.
- `ansible/playbooks/ada-ocb-preflight.yml`, `ada-ocb-verify.yml` — report builder branches on probe presence: unprobed hosts emit `probed:false/unreachable:true` reports (summary bucket `unreachable`, not `fail`); `ignore_unreachable` on the delegated fact-set; debug task names unprobed hosts.
- `ansible/playbooks/ada-ocb-audit.yml` — same crash class fixed: per-host template/verdict loops skip unprobed hosts.
- Trail doc: `docs/ssot/jobs/infrastructure/2026-11-26-ada-ocb-tony-dell-fallback.yml`.

## Verification (real playbooks on tony-dell controller, staged /tmp copy, removed after)

- `ada-ocb-verify --limit idc02,localhost` (the failing scenario): **PASS, exit 0** — `ok=1 drift=0 fail=0 unreachable=1 probed=1/2`; tony-dell report reads `unreachable role=fallback ... (no ocb_probe — excluded by --limit or host unreachable)`.
- `ada-ocb-verify` (full): **PASS** — `ok=2 probed=2/2`; idc02 `web=2.8.0 cli=2.4.2`, tony-dell `web=2.8.0 cli=2.4.1 local=200`.
- `ada-ocb-verify --limit tony-dell,localhost`: strict gate holds — fails loudly `idc02 is role=primary (strict) but produced no usable ocb_probe`; benchmark evidence still written via `always`.
- `ada-ocb-preflight --limit idc02,localhost`: PASS. `ada-ocb-audit --limit idc02,localhost`: no crash, unprobed host named/skipped.

## How to verify

From `ansible/` on any controller checkout containing this diff:
`ANSIBLE_CONFIG=./ansible.cfg ansible-playbook playbooks/ada-ocb-verify.yml --limit idc02,localhost` → expect PASS with tony-dell bucketed `unreachable`, not `fail`.

lessons:
- localhost report/assert phases looping `groups[...]` ignore `--limit` — guard fact access with `hostvars[h].x is defined` or collect probed hosts via `hostvars|dict2items|selectattr` (audit-log-shipper pattern).
- `delegate_to: "{{ item }}"` + `delegate_facts` still SSHes to limit-excluded hosts; truly unreachable ones need `ignore_unreachable` or the whole localhost play dies.
- benchmark-report-write already buckets `unreachable` — emit `probed:false/unreachable:true` + summary prefix `unreachable` and it counts correctly with zero template changes.
