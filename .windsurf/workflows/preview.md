---
description: Start a local chaba-h3 preview server
---
1. Check whether `0.0.0.0:8123` is already listening. If it is, reuse the existing server and skip to step 4.
2. // turbo
   Run `just -f /home/tony/CascadeProjects/chaba-h3/Justfile serve-php` in the background.
3. Wait for the server to listen on `0.0.0.0:8123`.
4. Open `http://192.168.1.48:8123` in the browser preview.
5. Report the server PID and keep it alive until the user says stop.
6. On `stop` or `/stop-preview`, terminate the server and confirm the port is free.
