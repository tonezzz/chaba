---
title: "Chaba status site deployment"
date: 2026-07-22
tags: [chaba, plesk, git, monitoring]
status: active
category: implementation
---

## Context

Chaba is a Node.js status-site project deployed at `https://chaba.h3.gizmo-thailand.com/`. Source is published in the public GitHub repository `tonezzz/chaba` on branch `chaba.h3`.

## Goal

Provide a private host inventory now, then add server-side live and last-known status monitoring.

## Decisions / why

| Date | Decision | Reason |
|------|----------|--------|
| 2026-07-22 | Deploy from Plesk Git using `chaba.h3` | GitHub-hosted FTPS deployments failed because the hosting FTP data connection was reset. |
| 2026-07-22 | Remove the GitHub FTPS workflow | Plesk Git is the single deployment path and avoids repeated failed GitHub Actions runs. |
| 2026-07-22 | Keep the host inventory free of internal IP addresses | The page must not expose private network details. |

## Notes

- Plesk Git deployment was tested with branch commits through `701c8e2`; later pushes use the same path.
- The host panel is available at `/hosts` and contains Tony Dell, Tony Omen, and Android TV Box as inventory entries.
- Nginx serves files in the Plesk document root directly, so Node-level Basic Auth does not protect static root files. Use Plesk directory protection for whole-site access control.

## Blockers

- No live monitor worker, database, or status history exists yet.

## Next steps

1. Enable Plesk directory password protection for the document root if the site should remain private.
2. Define monitored services and install a server-side monitor worker.
3. Persist current and historical check results, then replace the inventory-only statuses with live data.
