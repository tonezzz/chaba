---
description: Cleanup Docker disk usage on standalone host
---

Use this workflow when Portainer/Docker pulls fail with `no space left on device`, or when `/` is close to full.

1. Quick status (identify pressure)

```bash
df -h
sudo du -h -d1 /var/lib/docker 2>/dev/null | sort -h
sudo du -h -d1 /var/lib/containerd 2>/dev/null | sort -h

docker system df
```

2. Safe cleanup (does NOT delete running containers)

```bash
# Remove build cache (often safe + helpful)
docker builder prune -af

# Remove unused images (images not referenced by ANY container)
docker image prune -af

# Remove stopped containers + unused networks
docker container prune -f
docker network prune -f
```

3. Re-check

```bash
df -h
docker system df
```

4. If still full: trim Docker JSON logs (safe, but you lose old logs)

```bash
# Show largest container logs
sudo du -h /var/lib/docker/containers/*/*-json.log 2>/dev/null | sort -h | tail -n 20

# Truncate one large log (replace <container-id> accordingly)
# sudo truncate -s 0 /var/lib/docker/containers/<container-id>/<container-id>-json.log
```

5. If still full: vacuum systemd journal (safe)

```bash
sudo journalctl --disk-usage
sudo journalctl --vacuum-time=7d
```

6. DANGEROUS (only if you know volumes are disposable)

```bash
# This can delete persistent data (DBs, etc.)
docker volume prune -f
```

7. After cleanup: retry Portainer pull/deploy

- In Portainer:
  - Stack -> Update stack -> Pull and redeploy
