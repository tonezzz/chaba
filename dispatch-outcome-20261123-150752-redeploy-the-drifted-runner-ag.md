# Dispatch outcome — redeploy drifted runner-agent (speed-probe, attempt 2)

Card: `speed-probe`. Host: mn01. Date: 2026-11-23 ~22:30 +07.

## What was found

- **The drift had already self-healed on every reachable host.** Live
  `sha256sum` on idc03, idc02, tony-dell, tony-omen (and locally on mn01):
  both `~/.local/bin/runner-agent` and
  `~/CascadeProjects/chaba/scripts/board/runner-agent.py` are
  `d9af2b9cd9410faf…` == `origin/master:scripts/board/runner-agent.py`.
  runner-agent's `_self_update()` (no pin check, mtime-guarded) converged
  them once each exec checkout pulled commit `4fcfa5d8ea`.
- **Root cause of the recurring drift wave + fleet-health failures:**
  commit `4fcfa5d8ea` (today 18:48 +07, "runner-agent: carry kk_mac
  Ollama usage…") changed `runner-agent.py` **without bumping its content
  pin** in `scripts/devin/runner-tooling.manifest.json` (pin still
  `bf445389` = pre-commit bytes). Consequences: `sync-runner-tools.sh`
  refuses the install fleet-wide ("src sha != pinned sha"), every
  `runner-auto-*` card reports `checkout/installed sha != pin`, and
  `tests/board/test_runner_tooling_contract.py` fails on master.
- **tony-macbook is SSH-unreachable fleet-wide** — `Permission denied
  (publickey,password)` for every key tried: mn01's four keys direct to
  `100.77.76.112`, tony-omen's `id_ed25519_macbook`, tony-dell's
  `id_cascade`; `tailscale ssh` has no advertised host key (not enabled
  on the node). This matches the `runner-auto-tony-macbook` card's
  "probe failed" note. **However its runner is provably NOT drifted:** it
  claimed `distiller-enrich-productionize` (22:04) and
  `kk-ha-degraded-mode-explain-capabilities-000d8b` (22:05) tonight, and
  `_claimable` returns the stale reason before any claim — claims flowing
  ⇒ `self_stale_reason()==""` ⇒ installed == its checkout ref. Whether
  that ref is already `d9af2b9c` or the prior `bf445389`, it converges via
  its own repo-sync + `_self_update`; no scp is possible or needed.

## What was done

1. Verified sha parity on all reachable hosts, then re-installed per spec
   anyway: `install -m 0755 ~/CascadeProjects/chaba/scripts/board/
   runner-agent.py ~/.local/bin/runner-agent` on idc03, idc02, tony-dell,
   tony-omen — all now `d9af2b9c`, mode 755 (repo file is 664; the unit
   `ExecStart=%h/.local/bin/runner-agent` needs +x, so `install -m 0755`,
   not bare scp).
2. Forced/observed runner-agent passes: idc03 + idc02 fresh
   `systemctl --user start` → `Result=success`, `ExecMainStatus=0`,
   zero drift/traceback in journal (remaining gates are routine load/cap
   defers). tony-dell + tony-omen: `Result=success`, clean journals,
   claim passes every ~60s.
3. Fixed the pin bug on this branch: `runner-tooling.manifest.json`
   runner_agent `sha256` → `d9af2b9c…`, `updated` → 2026-11-23. Commit
   `171209ee93`. `test_runner_tooling_contract` 7/7 OK; all six pins
   re-verified against sources.
4. Posted outcome comms to `speed-probe` and an access/health note to
   `runner-auto-tony-macbook`.

## Result

Done for every host that can be reached: idc03, idc02, tony-dell (the
card's named set) plus tony-omen and mn01 — installed runner-agent is
byte-identical to origin/master `d9af2b9c` and services run clean with no
drift errors. tony-macbook: redeploy impossible (no SSH path exists from
any fleet host) but also unnecessary — its runner is demonstrably
un-drifted and self-converges; the broken SSH/probe path is the real
follow-up, already carded on `runner-auto-tony-macbook`.

## How to verify

```sh
# per host — both lines must print the same sha (d9af2b9c…)
ssh <host> 'sha256sum ~/.local/bin/runner-agent \
  ~/CascadeProjects/chaba/scripts/board/runner-agent.py; \
  stat -c %a ~/.local/bin/runner-agent'
# service health — Result=success, no "drift"/"traceback" hits
ssh <host> 'systemctl --user show runner-agent.service \
  -p Result,ExecMainStatus; \
  journalctl --user -u runner-agent.service --since -15min | grep -i drift'
# tony-macbook indirect proof — fresh claims imply not drifted
curl -s 'https://idc03.taila0626a.ts.net:10000/host-status?host=tony-macbook'
# pin fix — once 171209ee93 merges, fleet-health + contract test go green
python3 tests/board/test_runner_tooling_contract.py   # in a checkout with the merge
```

lessons:
- runner-agent `_self_update()` ignores the manifest pin (mtime-guard only) while `sync-runner-tools.sh` enforces it — a source change without a pin bump self-heals installed copies but silently breaks the sync path + fleet-health + contract test. Check `runner-tooling.manifest.json` sha vs `sha256sum scripts/board/runner-agent.py` after any runner-agent commit.
- `_self_stale_check`/`_claimable` gate every claim on installed==checkout-ref bytes — a host actively claiming cards is proof its runner-agent is NOT drifted; use `/host-status?host=` claim ages as off-host drift evidence when SSH is dead.
- `~/.local/bin/runner-agent` must stay mode 755 (`ExecStart=` execs it directly; repo source is 664) — redeploy with `install -m 0755`, not bare `scp` which can drop the exec bit.
- tony-macbook SSH is broken fleet-wide (all keys rejected from mn01/omen/dell; no tailscale-ssh host key) — runner still works, but any task needing on-host shell access there is blocked until keys/console are repaired (tracked on runner-auto-tony-macbook).
- origin/master moves fast (24 commits during this session, mostly board-api churn) — re-check `git show origin/master:scripts/board/runner-agent.py | sha256sum` before pinning; the sha was stable at d9af2b9c across the window.
