# SUBAGENT CONTRACT: Tony-Dell Podman Migration — Destructive Steps

## Scope

This contract documents the destructive steps identified during the review of `docs/ssot/ssot.focus.yml` focus item **tony-dell podman service migration** and the related SSOT files.

## Status at time of review (2026-08-18)

No destructive commands were executed because the target containers are **already absent** on `tony-omen`:

- No `postgres` container is running or stopped on `tony-omen`.
- No `ghcr.io/github/github-mcp-server` containers (musing_bohr, thirsty_nobel, sleepy_ritchie, blissful_bassi, frosty_mcclintock, frosty_noether) are present.
- All tony-dell Podman services have Quadlet units and are `systemctl --user enabled`.

This contract is retained as the required pre-approval record for the exact commands that would be executed if the work were not already done.

## Subtask 2 — Decommission tony-omen duplicate postgres container

### Proposed commands

```bash
# 1. Confirm the target is the duplicate, not the primary
ssh tony-dell.local 'systemctl --user is-active chaba-postgres-16'
docker ps -a --filter 'name=postgres' --format '{{.Names}}\t{{.Image}}\t{{.Status}}'

# 2. Stop and remove only the tony-omen duplicate
TARGET=$(docker ps -aq --filter 'name=postgres' | head -n1)
[ -n "$TARGET" ] && docker stop "$TARGET" && docker rm "$TARGET"

# 3. Optional: reclaim image/volume (destructive — requires separate approval)
# docker image rm pgvector/pgvector:pg16
# docker volume rm <omen_postgres_volume>
```

### Impact

- Removes the old PostgreSQL container from `tony-omen`, freeing disk and eliminating the duplicate.
- If the wrong container is removed, `yomi-api` and dependent services on `tony-omen` could lose database connectivity; failover to `tony-omen` would fail.
- Rollback: restore from the latest `chaba-latest.dump` on `tony-omen:/home/tony/backups/yomi/` per `ssot.yomi-failover.yml`.

## Subtask 3 — Remove six duplicate github-mcp-server containers on tony-omen

### Proposed commands

```bash
# 1. List the stale containers and remove them by name
for c in musing_bohr thirsty_nobel sleepy_ritchie blissful_bassi frosty_mcclintock frosty_noether; do
    docker rm -f "$c" 2>/dev/null && echo "removed $c" || echo "$c not found"
done

# 2. Clean up any leftover ghcr.io/github/github-mcp-server image
 docker image rm ghcr.io/github/github-mcp-server:latest 2>/dev/null || true
```

### Impact

- Removes stale GitHub MCP server containers that leaked from `docker run -i --rm` invocations.
- No running service depends on these containers; impact is low.
- Rollback: re-pull `ghcr.io/github/github-mcp-server:latest` and re-run the caller; no persistent data is lost.

## Preconditions before any of the above destructive commands are run

1. `tony-dell` is reachable and `chaba-postgres-16` Podman service is active and healthy.
2. `ssot.yomi-failover.yml` primary disposition is confirmed.
3. A fresh backup exists at `tony_omen:/home/tony/backups/yomi/chaba-latest.dump`.

## Approval

Do **NOT** run the commands above without explicit user confirmation.
