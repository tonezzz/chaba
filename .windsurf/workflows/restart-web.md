---
description: Restart the Caddy web Docker stack
---
1. Run `just -f /home/tony/CascadeProjects/chaba/Justfile restart-web`.
2. Run `docker ps --filter name=web` to confirm the web container is running.
3. Optionally verify `http://192.168.1.48:8080/` returns HTTP 200 with `curl -I`.
4. Report when it is ready.
