---
description: Regenerate Frigate config and restart the NVR
---
1. Confirm with the user before regenerating config and restarting Frigate. If they agree, proceed.
2. Run `just -f /home/tony/CascadeProjects/chaba-tony-dell/Justfile rebuild-cameras`.
3. Restart Frigate with `just -f /home/tony/CascadeProjects/chaba-tony-dell/Justfile restart-frigate`.
4. Wait 10 seconds, then check `docker ps` for the frigate container.
5. Verify the web UI is reachable: `curl -I http://tony-omen.local:5000/`.
6. If the UI is not reachable, show `docker logs frigate --tail 50` for diagnosis.
7. Report when it is ready.
