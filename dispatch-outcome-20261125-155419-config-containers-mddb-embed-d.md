# Dispatch outcome — idc03-stale-embed-db-delete

Card: `idc03-stale-embed-db-delete` (MEM-0071) — delete stale
`~/.config/containers/mddb-embed/data/mddb.db` (2.8G) on idc03 after the
~2026-11-19 rollback window; live bank on idc02.

## Result: already done — verified end-state, nothing to delete

The stale directory no longer exists on idc03. Verified 2026-11-25:

- `ls ~/.config/containers/mddb-embed` on idc03 → No such file or
  directory; the containers dir holds only caddy, mddb, mddb-cms,
  mddb-ops, postgres, redis, systemd.
- The retired quadlet `~/.config/containers/systemd/
  mddb-embed.container.retired` (Nov 8) shows the volume was
  `.../mddb-embed/data:/app/data:U` — exactly the path that is now
  absent.
- `find /home/tony -xdev -name '*.db' -size +100M` on idc03: only the
  live idc03 banks (mddb 5.6G, mddb-cms 19.6G, mddb-ops 8.1G — all
  written today), `~/mddb-backups/` nightly dumps of those banks
  (declared backup tier), and unrelated HA/device DBs. No embed-bank
  copy anywhere.
- `podman ps -a` / `podman volume ls` on idc03: no mddb-embed
  container or volume.

Removal likely happened during the post-2026-11-19 cleanup window once
the rollback copy was no longer needed; no record of who/when (no
bash-history hit, retired unit has no journal).

## Live bank on idc02 — consumer-verified healthy

- `mddb-embed.service` active since 14:35 +07; container `mddb-embed`
  up ~1h; live DB 3.77G at
  `~/.config/containers/mddb-embed/data/mddb.db`, mtime 15:50 today.
- `GET http://100.123.163.11:11028/health` → 200
  `{"status":"healthy","mode":"wr","durable":true,...}`.

## Deliverables

- Trail doc: `docs/ssot/jobs/mddb/2026-11-25-idc03-stale-embed-db-delete.yml`
- Card comms updated via board-api; card ready for dispatcher close.

## How to verify

```
ssh idc03 'ls ~/.config/containers/mddb-embed'        # absent
ssh idc03 'find /home/tony -xdev -name "*.db" -size +100M'  # no embed db
curl -s http://100.123.163.11:11028/health            # healthy/wr
```

lessons:
- Dated-reminder delete cards can arrive after the target is already
  gone — verify absence (ls + find for stray copies) rather than
  assuming the delete still needs doing; the card still closes on
  verified end-state.
