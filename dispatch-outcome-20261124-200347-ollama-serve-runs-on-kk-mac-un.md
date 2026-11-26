# dispatch outcome — kkmac-ollama-durable-bind (attempt 2)

Card: `kkmac-ollama-durable-bind` — make kk-mac ollama reachable durably.

## What the card asked vs what was found

Spec offered (a) declared ssh-tunnel unit on idc03 ★ or (b) `OLLAMA_HOST`
bind on adanest's plist. Live verification (attempt 1, 18:41 dispatch)
showed **(b) already landed 2026-11-19**: adanest's
`net.adanest.ollama` LaunchDaemon binds `0.0.0.0`, answers on tailnet
`100.108.217.17:11434`, the idc03 admission shim (`:11447`) and
embed-pool already upstream the direct bind, and the `:11445` tunnel was
disabled after ~19k restart flaps — nothing consumes it, so (a) was moot.
Attempt 1 shipped the repo-truth sync (commit `ffbd55a36c`) but its push
was rejected (fetch first) and the branch never merged.

This attempt carried that commit forward (cherry-pick, one SSOT
conflict resolved), fast-forwarded onto current master, and re-verified
everything live.

## Verified live this session (2026-11-24 ~20:1x +07)

- `curl http://100.108.217.17:11434/api/version` → `{"version":"0.40.8"}`
- Via `ssh idc03 → ssh kkkakk@kk-mac`:
  - `launchctl print system/net.adanest.ollama` →
    `OLLAMA_HOST => 0.0.0.0:11434` in EnvironmentVariables of
    `/Library/LaunchDaemons/net.adanest.ollama.plist` (root:wheel);
    `plutil -p` confirms the same. **Bind durability VERIFIED — survives
    reboot by construction.** No adanest access needed (system domain is
    world-readable to any ssh user).
  - `curl` from kk-mac itself: `:11434` answers on tailnet
    `100.108.217.17`, LAN `192.168.0.101`, **and** LAN `192.168.2.90` —
    the LAN exposure is real on both home subnets.
  - `kkkakk` has no passwordless sudo; `adanest@kk-mac` ssh is denied
    from idc03, tony-omen, and tony-dell — the narrow-bind fix remains
    KK-sudo-gated.
- idc03 `kkmac-ollama-tunnel.service`: loaded, `disabled`, `inactive` —
  matches repo declaration.

## What changed (commit `a28407a11f` on this branch)

- `stacks/idc03/litellm/kkmac-ollama-tunnel.service` — new: declares the
  disabled fallback unit (deploy.sh installs it, never enables).
- `stacks/idc03/litellm/kkmac-admission-shim.service` — matches live
  hand-edit (`KK_SHIM_UPSTREAM=http://100.108.217.17:11434`, dropped the
  tunnel `After=` dep).
- `stacks/idc03/litellm/config.yaml`, `deploy.sh` — comments/units list
  updated for direct-bind-primary, tunnel-as-fallback.
- `docs/ssot/infrastructure/ssot.llm-gateway.yml` +
  `ssot.audit.hosts.yml` — ollama-kkmac provider note, tunnel
  `expected_state: inactive`, kk-mac `capabilities.ollama` rewritten for
  the 0.0.0.0 bind with both LAN IPs and the durability verification.
- `docs/ssot/jobs/devnest/2026-11-24-kkmac-ollama-durable-bind.yml` —
  job trail: verified/pending/rollback.
- `docs/kb/kkmac-ollama-lane.md`, `docs/kb/opencode-lane-model-notes.md`
  — spec-required update: direct tailnet bind, disabled tunnel fallback,
  rollback path, security note.
- `docs/kb/ada-nest-kk-mac-onboarding.md` — fixed plist-name drift
  (`ai.adanest.ollama` → `net.adanest.ollama`) and stale "binds
  127.0.0.1 by design" note.
- `scripts/ops/kk-mac-onboard.sh` — plist generation synced to the live
  daemon: label `net.adanest.ollama`, full env set
  (FLASH_ATTENTION/KV_CACHE_TYPE/MAX_LOADED_MODELS/NUM_PARALLEL/
  MODELS), `GroupName=staff`, log paths `/Users/adanest/ollama.{log,err}`,
  `OLLAMA_BIND` default `0.0.0.0:11434` matching live. Without this, a
  re-run would have written a divergent `ai.adanest.ollama` plist.

## Result

- Card goal (durable reachability) is **met and verified**: the bind is
  in the LaunchDaemon plist (reboot-safe), fleet path is declared in
  repo, tunnel demoted to a declared fallback.
- One open item raised as board request
  `kk-mac-ollama-binds-0-0-0-0-lan-exposed-6d42d5`: narrow
  `OLLAMA_HOST` to `100.108.217.17` — needs KK's sudo on kk-mac; exact
  commands are in the request and the job doc.

## How to verify

- `ssh idc03 'ssh kkkakk@kk-mac "plutil -p /Library/LaunchDaemons/net.adanest.ollama.plist"'` — OLLAMA_HOST present.
- `curl -s http://100.108.217.17:11434/api/version` → 0.40.8.
- `systemctl --user status kkmac-ollama-tunnel.service` on idc03 → disabled/inactive.
- `git show a28407a11f --stat` on branch `dispatch/20261124-200347-ollama-serve-runs-on-kk-mac-un`.

lessons:
- `launchctl print system/<label>` + `plutil -p` on `/Library/LaunchDaemons/*.plist` are world-readable as any ssh user on macOS — system-domain daemon config verifies WITHOUT the service account's credentials. Don't assume adanest access is needed to verify a system LaunchDaemon.
- zsh on macOS treats `=word` as command-path expansion — `echo ===X===` fails with "==X== not found"; quote it.
- `git stash`/`cherry-pick --no-commit` leave unmerged index entries that silently break a later `git stash` ("needs merge / could not write index") — `git add` resolved conflict files before stashing.
- Shared git stash across worktrees: `stash@{0}` may be another session's autostash — check `git stash list` before pop.
- kk-mac has TWO LAN interfaces answering ollama (192.168.0.101 en0? + 192.168.2.90) — "the LAN IP" is ambiguous; enumerate `ifconfig` before documenting exposure.
