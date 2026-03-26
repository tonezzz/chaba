# Cleanup: Docker disk full (Portainer pull fails)

Operator SSOT:

- `services/assistance/docs/ACTION.md`

## Symptom

Portainer stack deploy/pull fails with errors like:

- `failed to copy: failed to send write: ... no space left on device`

Often the host root filesystem is full (e.g. `/dev/sda1` at 100%), and the image pull cannot write into:

- `/var/lib/docker` (Docker)
- `/var/lib/containerd` (containerd content store)

## Fast remediation (standalone Docker host)

1. Check disk pressure

```bash
df -h
docker system df
```

2. Safe cleanup (does NOT delete running containers)

```bash
# Build cache
docker builder prune -af

# Unused images (not referenced by ANY container)
docker image prune -af

# Stopped containers + unused networks
docker container prune -f
docker network prune -f
```

3. Re-check

```bash
df -h
docker system df
```

4. If still full: truncate huge container JSON logs (safe, but old logs are lost)

```bash
sudo du -h /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -h | tail -n 20
# sudo truncate -s 0 /var/lib/docker/containers/<container-id>/<container-id>-json.log
```

5. If still full: vacuum systemd journal

```bash
sudo journalctl --disk-usage
sudo journalctl --vacuum-time=7d
```

6. Dangerous (only if you know volumes are disposable)

```bash
# Can delete persistent data (DBs, etc.)
docker volume prune -f
```

## Diagram (decision flow)

```mermaid
flowchart TD
  A[Portainer pull/deploy fails] --> B{Error includes\nno space left on device?}
  B -- No --> Z[Not disk related\nCheck registry/auth/network]
  B -- Yes --> C[Check disk: df -h\nCheck docker usage: docker system df]
  C --> D{Root (/) or docker dir near full?}
  D -- No --> Z2[Check inode exhaustion\n(df -i) and logs]
  D -- Yes --> E[Run safe cleanup\nbuilder prune + image prune\ncontainer/network prune]
  E --> F{Enough space freed?}
  F -- Yes --> G[Retry Portainer pull/redeploy]
  F -- No --> H[Truncate large Docker JSON logs]
  H --> I{Enough space freed?}
  I -- Yes --> G
  I -- No --> J[Vacuum journalctl]
  J --> K{Enough space freed?}
  K -- Yes --> G
  K -- No --> L[Last resort: volume prune\n(only if safe)]
  L --> G
```

## Notes

- Prefer pruning **images** first when `docker system df` shows huge image usage.
- If `/` hits 100%, Docker/containerd can fail in unexpected ways (pulls, restarts, etc.).
- After cleanup, redeploy via Portainer:
  - Stack -> Update stack -> Pull and redeploy
