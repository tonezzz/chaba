# Caddy snippet for Jarvis under /jarvis

Assumes:
- Caddy runs on the host
- The Portainer stack publishes container ports to localhost:
  - Frontend: `127.0.0.1:18080`
  - Backend: `127.0.0.1:18018`

```caddy
assistance.idc1.surf-thailand.com {
  # WebSocket endpoint to backend (strip /jarvis prefix)
  handle_path /jarvis/ws/* {
    reverse_proxy 127.0.0.1:18018
  }

  # All other /jarvis paths go to the SPA frontend
  handle_path /jarvis/* {
    reverse_proxy 127.0.0.1:18080
  }
}
```

Notes:
- `handle_path` strips the matched prefix before proxying.
  - `/jarvis/ws/live` becomes `/ws/live` at the backend.
  - `/jarvis/...` becomes `/...` at the frontend.
- WebSockets work automatically through `reverse_proxy`.
