# Dispatch outcome — dispatch-capacity-bench

## What was done

Benchmarked dispatch capacity per host and evaluated bare systemd-run vs
podman-wrapped devin-task. Full write-up: `docs/assessments/dispatch-capacity-2026-10.md`
(raw monitor logs in `docs/assessments/dispatch-capacity-2026-10/`), job
record at `docs/ssot/jobs/infrastructure/2026-10-04-dispatch-capacity-bench.yml`.

## Key measurements

- tony-dell bare path: dispatch→unit ~6.5 s (worktree), unit→first
  transcript ~23 s. Trivial task cgroup peak 549–660 MB (n=3, all rc=0);
  a real npm task peaked **1.07 GB** — use ~1.1 GB/task for capacity math.
- 4 concurrent sessions on dell → MemAvailable min 3.1 GB; cap=3 validated.
- Card premise corrected: tony-omen AND mn01 already have devin
  3000.10.31 + credentials.toml + devin-dispatch — bare-dispatchable today.
- idc02 podman: devin-dispatch image 402 MB, container start ~0.27 s vs
  systemd-run ~0.02 s; rootless `--memory`/`--cpus` caps verified in
  container cgroup. `devin -p` reaches login — only auth is missing.

## Recommendation

tony-dell bare + `MemoryMax=1536m` (units are unbounded today); omen/mn01
bare (caps 2/1); idc02 first podman runner (cap 4); avoid idc01 (prod).
Podman wins where the CLI isn't installed; bare wins where it already is.

Update 2026-10-05: Tony chose per-host credential copies (board answer
"b"); `credentials.toml` + `config.json` provisioned on idc02 and
`devin -p` verified end-to-end inside the rootless container (rc=0) —
the podman runner path is fully proven. Verified run recipe is in the
assessment section 4.

## How to verify

`docs/assessments/dispatch-capacity-2026-10.md` sections 1–5; raw logs
`t1-unit.log` / `t2-units.log` show per-2s cgroup samples; idc02 results
reproducible via `ssh idc02 'podman run --rm devin-dispatch:test devin --version'`.
