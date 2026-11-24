# Dispatch outcome — ada-scenario-quadlets-exit-contract

## What was done

Deployed the OPS-0581 exit-contract shim for the scenario quadlets on idc03 and
redeployed runner-agent on idc03 + mn01.

1. **idc03 install.sh** — ran `bash install.sh` in
   `~/CascadeProjects/chaba/stacks/services/ada-scenario-runner` on idc03.
   The checkout already carried the fix (commit `1f3b48b225`,
   `container-suite-run.sh` + `ENTRYPOINT` in the Containerfile).
   - podman image `localhost/ada-scenario-runner:latest` rebuilt
     (`4494ce2aac4a`, created 2026-11-24 14:39 UTC).
   - `ENTRYPOINT ["/usr/local/bin/container-suite-run"]` confirmed via
     `podman inspect`; shim script content verified inside the image.
   - Quadlets re-installed to `~/.config/containers/systemd/`
     (`ada-scenario-smoke.container`, `ada-scenario-full.container`).
   - All timers armed; `ada-scenario-smoke.timer` next fires 22:00 +07,
     hourly thereafter — the first real exercise of the new entrypoint.

2. **runner-agent redeploy** — copied `scripts/board/runner-agent.py` to
   `~/.local/bin/runner-agent` on idc03 and mn01, `chmod 0755`, sha256
   verified `a08451d98f888544fd49c406ebee5683d82aca034362ab1956aea08a655c008a`
   on both (already converged via self-update; re-installed anyway per spec).

## Result

Done-condition met: install script and runner-agent updates ran without
errors on the target hosts. Completed-but-failing scenario runs now exit 0
when the final `N scenarios:` marker is present; real crashes still exit
nonzero.

## How to verify

- `ssh idc03 'podman inspect localhost/ada-scenario-runner:latest --format "{{.Config.Entrypoint}}"'`
  → `[/usr/local/bin/container-suite-run]`
- `ssh idc03 'systemctl --user list-timers | grep scenario'` → smoke hourly.
- After the next smoke run: `systemctl --user status ada-scenario-smoke`
  should show `result=success` even if scenarios fail.
- `sha256sum ~/.local/bin/runner-agent` on idc03/mn01 == repo copy.

lessons:
- runner-agent drift self-heals via `_self_update`/sync-runner-tools — always sha256-check before assuming drift; re-install is still cheap insurance.
- idc03's `~/CascadeProjects/chaba` exec checkout had dirty unrelated files but carried the needed stack commit; install.sh runs fine from it.
