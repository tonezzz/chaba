# Checklist
- Aim for doing the job hands-off: commit+push as much as possible before waiting to deploy.
- Aim for modularity: simple code structure for easy debugging.
- "system reload" only loads the system sheet.
- memo/memory/knowledge are ingested only when enabled, and loaded/updated.

Alignment with `ACTION.md`:
- Use `ACTION.md` as the operator playbook.
- Use this file as the requirements+results snapshot.

## Requirement list (compiled) + result

| Requirement | Result | Evidence / notes |
| --- | --- | --- |
| Selective CI builds: only build/push Docker images affected by changes | Done | `.github/workflows/publish-idc1-assistance.yml` change detector per matrix entry |
| Shared-path rebuild rules for cross-context dependencies | Done | `mcp-bundle` rebuild triggers on changes under `services/assistance/mcp-bundle/` |
| Immutable image tags for deterministic deploy verification | Done | Publish workflow pushes `:sha-<full>` and `:sha-<short>` tags + `:<branch>` |
| Deploy script supports Git-backed Portainer stacks without converting to file-based | Done (manual fallback) | `scripts/deploy-idc1-assistance.sh` attempts Git redeploy; on failure exits non-zero and instructs UI redeploy |
| Rely only on Portainer env; do not commit stack `.env` files | Done | Removed `stacks/idc1-assistance/.env` from repo and `.gitignore` exception removed |
| Prove redeploy updated even when `/health` lacks build identity | Done | Portainer API image inspect (`RepoDigests`) + `docker buildx imagetools inspect` digest match against SHA tag |
| GitHub Actions watcher: start -> visible state -> auto-stop on completed | Done | Verified `POST /github/actions/watch/start` + `GET /github/actions/watch/list` shows `stopped_reason=completed` |
| Operator playbook stays actionable (ACTION.md updated as we go) | Done | Status chart filled, SHA tag policy documented, watcher SNA section usable |

## Suggested improvements

| Area | Suggestion | Why |
| --- | --- | --- |
| Deployment verification | Add build identity into `/health` (e.g., env `BUILD_GIT_SHA`, `BUILD_IMAGE_TAG`) | Avoid needing Portainer inspection to prove code identity |
| Git-backed Portainer redeploy | Investigate Portainer CE 2.33.x Git redeploy `.env` requirement and document workaround | Current API path fails with missing `.env`; manual UI redeploy required |
| Watcher observability | Document/implement explicit UI log query endpoint in ACTION.md (and verify event kinds) | Current SNA verifies state via watch endpoints, but UI-log check is manual/implicit |
| Docs hygiene | Replace placeholder timestamps (e.g. `Snapshot ts`) with scripted capture snippet | Reduce manual edits and drift |
