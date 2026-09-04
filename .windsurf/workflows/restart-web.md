---
description: Restart the Caddy web Docker stack
---
1. Confirm with the user before restarting the web stack. If they agree, proceed.
2. Run `just -f /home/tony/CascadeProjects/chaba-tony-dell/Justfile restart-web`.
3. Run `docker ps --filter name=web` to confirm the web container is running.
4. Verify both endpoints return HTTP 200:
   - `curl -I http://tony-omen.local:8080/`
   - `curl -I http://tony-omen.local:8081/`
5. Report when it is ready, or surface any errors and relevant logs.
