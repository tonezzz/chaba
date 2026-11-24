# Dispatch outcome — helm-retirement (attempt 2)

## What this was

Card `helm-retirement` (done since 2026-09-30; deep cleanup finished under
OPS-1310 / `helm-retire-leftovers` on 2026-11-23, commit `df27d73d23`).
Attempt 1 did not merge/verify cleanly; this run re-audited every `helm`
reference in the repo and removed the residuals OPS-1310 missed.

## Verified already-retired (no action needed)

- Edge route `/apps/helm` and `@apps_helm` Caddy block — removed by OPS-1310;
  `stacks/web/Caddyfile`, `scripts/render-routes.py`, `ssot.routes.yml` clean.
- Static bundle `stacks/web/public/apps/helm/` — deleted by OPS-1310.
- `ssot.apps.helm.yml` — `status: retired`, `retired: 2026-11-23`,
  `restore_runbook: docs/kb/retired-apps/helm.md`.
- `helm.service` on idc02 (this host) — verified live: quadlet file exists
  only as `~/.config/containers/systemd/helm.container.disabled-ops1310`;
  no active unit, no podman container, nothing on :3003.
- `ssot.migrated-units.yml` helm entry already carries
  `state: retired 2026-11-23 (OPS-1310)`.
- safe-executor lesson for Ada — already filed by the OPS-1310 run.

## Removed in this run (residuals OPS-1310 missed)

- `stacks/web/docker-compose.prod.yml` — orphaned `helm:` service block
  (production profile; no base-service counterpart, stale DATABASE_URL).
- `stacks/web/docker-compose.secrets.yml` — `helm:` secrets attachment.
- `stacks/web/.env.example`, `stacks/web/.env.production` — `HELM_*` vars.
- `docs/runbooks/production-deployment-operations.md` — `### Helm Service`
  section and two `docker compose logs … helm` lines.
- `scripts/audit-hosts.py` + `ansible/playbooks/audit-fleet-services.yml` —
  `helm` dropped from the fleet-unit classifier regexes (kept in sync per
  the parity comment in the playbook).
- `docs/ssot/infrastructure/ssot.gemini-models.yml` — `helm-llm` fallback
  lane deleted; "for Helm"/"in Helm"/"Helm LLM provider" notes corrected.
- `ssot.gemini-models.gemini-2.5.yml` — `primary_for: [helm-llm]` removed
  from gemini-2.5-flash (still used as fallback in yomi/media lanes).
- `ssot.gemini-models.gemini-3.yml` — `fallback_for: [helm-llm]` removed
  from gemini-3.5-flash-lite; note rewritten without the dead consumer.
- `.prettierignore` — stale `stacks/web/public/apps/helm/` entry.
- `docs/ssot/infrastructure/ssot.workspaces.yml` — helm repo purpose
  corrected from "helm charts" to retired app source + runbook pointer.

## Deliberately left (historical/false-positive)

- `docs/kb/retired-apps/helm.md`, `ssot.containerization.yml` migration
  log, focus/archive/jobs/evals/reports/backups — point-in-time records.
- `project-health/index.html` Helm alert row — frozen 2026-09-28 snapshot.
- `figma-gallery/generated/apps-landing.tsx` "🎯 Helm" card — generated
  Figma design mockup, no generator in repo.
- `helm` in `session_artifacts.py` regex = Kubernetes helm CLI, unrelated;
  `helm`/`helmina`/`overwhelming` hits in gev assets and yomi js = false
  positives.

## How to verify

- `git show --stat` on this branch's commit; `grep -rn -i helm` shows only
  the historical/false-positive files listed above.
- `python3 -c "import yaml; yaml.safe_load(...)"` passes on all edited YAML.
- On idc02: `systemctl --user list-units | grep helm` → nothing;
  `ls ~/.config/containers/systemd/ | grep helm` → only `.disabled-ops1310`.

lessons:
- OPS-1310-style cleanups miss compose overrides, .env files, audit regexes,
  and model-consumer SSOT lanes — a repo-wide `grep -i helm` after any app
  retirement catches the stragglers.
- board-api is not on localhost for idc02 dispatches; reach it via
  `ssh idc03 'curl -s -X POST http://127.0.0.1:8787/...'`.
- audit-hosts.py FLEET_SYS_RE and the ansible playbook fleet_sys_re must be
  edited together — the playbook comment demands parity.
