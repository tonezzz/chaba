# Helm Dashboard — retired 2026-11-23 (OPS-1310)

Former asset: `docs/ssot/apps/ssot.apps.helm.yml` (`status: retired`). Former URL: `https://tony-dell.taila0626a.ts.net/apps/helm/`, upstream `idc02.taila0626a.ts.net:3003` (tailnet-IP bind `100.123.163.11:3003`).

## Why retired
The original helm-retirement card was closed 2026-09-30 ("superseded by project-health/focus/SSOT stack") but leftover service, route, static bundle and SSOT entries remained. Tony confirmed retirement again 2026-11-09. Consumer audit 2026-11-23 found no app tile, no code consumers and no human sessions — the only traffic was the generic 5-minute `check-routes.py` probe, which disappears with the route. Audit evidence: `idc02-consumer-audit-ops1310-ops1312.md` in the infra workspace.

## What was removed (chaba commit on `retire/ops-1310-helm-leftovers`)
- `stacks/web/Caddyfile`: `@apps_helm` / `handle @apps_helm` block.
- `scripts/render-routes.py`: `CUSTOM_BLOCKS["helm"]`.
- `docs/ssot/infrastructure/ssot.routes.yml`: `helm` listener and proxy route.
- `stacks/web/public/apps/helm/`: built static bundle.
- `helm.service` on idc02: stopped and disabled (was a podman/quadlet container, `unit_file: %h/.config/containers/systemd/helm.container`).
- Stale monitoring/config references: `ssot.health.home.web.yml`, `ssot.health.mobile.yml`, `ssot.health.yml`, `ssot.mcp.yml`, `ssot.audit.hosts.yml`, `ssot.migrated-units.yml`.

## Source state (recorded per card spec)
- `/home/tony/CascadeProjects/helm` on idc02: directory exists but contains **only `.env.local`** (208 bytes, 2026-10-17). Not a git repo; no source code.
- Full source is still on **tony-omen** at `/home/tony/CascadeProjects/helm/src/lib/ai/{safe-executor,intent-parser,task-planner}.ts` (and the rest of the tree). It was not deleted — this retirement only removes the running service and its web surface.
- Code was deliberately **not ported**. The AJ/ADA concepts worth noting were filed as a lesson instead (see below).

## Restore steps (if ever needed)
1. On tony-omen, confirm the source tree at `/home/tony/CascadeProjects/helm` is intact; build the Next.js app (`npm run build`) and copy the built `out/`/static bundle back to `stacks/web/public/apps/helm/` in the chaba checkout.
2. Recreate the quadlet unit on idc02: `~/.config/containers/systemd/helm.container` listening on `100.123.163.11:3003` with `Host: localhost` rewrite expected at the edge; `systemctl --user daemon-reload && systemctl --user enable --now helm`. Verify `curl -s -o /dev/null -w '%{http_code}' http://100.123.163.11:3003/apps/helm/` returns 200/308.
3. Restore the `@apps_helm` block in `stacks/web/Caddyfile` and `CUSTOM_BLOCKS["helm"]` in `scripts/render-routes.py`, re-add the listener + proxy route to `docs/ssot/infrastructure/ssot.routes.yml`, then `python3 scripts/render-routes.py --caddy && python3 scripts/render-routes.py --check`.
4. Sync the Caddyfile to tony-dell's `chaba-tony-dell/stacks/web/Caddyfile` and restart the bind-mounted container: `systemctl --user restart web` (a bare `caddy reload` serves the stale inode — see `docs/kb/host-reboot-verification.md:178-183`). Verify `curl -s -o /dev/null -w '%{http_code}' https://tony-dell/apps/helm/` returns 200.
5. Re-add the health/monitoring entries removed above and set `ssot.apps.helm.yml` back to `status: active`.

## Lesson filed
A short lesson was filed via `scripts/lesson-add.py` on the safe-executor validation patterns (sandbox path containment, pre-flight lint/typecheck/tests/build gates, backup + auto-rollback, approvalRequired by risk level). Verdict: the patterns may inform Ada tool design, but the specific implementation is superseded by board-api validated endpoints — do not port the code.
