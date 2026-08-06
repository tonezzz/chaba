---
name: docker-restart
description: Restart chaba web stack with confirmation
allowed-tools:
  - exec
triggers:
  - user
---

Restart the chaba web stack:

1. Ask the user for confirmation before proceeding
2. Check current docker compose status: `docker compose ps`
3. Restart the web stack: `docker compose restart`
4. Wait a few seconds for services to start
5. Verify key endpoints are responding:
   - Check http://localhost:8080/ returns 200
   - Check http://localhost:8081/ returns 200
6. Report the restart status and any issues
