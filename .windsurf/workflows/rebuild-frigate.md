---
description: Regenerate Frigate config and restart the NVR
---
1. Run `just -f /home/tony/CascadeProjects/chaba/Justfile rebuild-cameras`.
2. Restart Frigate with `just -f /home/tony/CascadeProjects/chaba/Justfile restart-frigate`.
3. Wait 10 seconds, then check `docker ps` for the frigate container.
4. Optionally verify the Frigate web UI is reachable on its configured port.
