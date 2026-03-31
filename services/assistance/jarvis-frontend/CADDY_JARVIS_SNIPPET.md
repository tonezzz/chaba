# Caddy snippet for Jarvis under /jarvis

Assumes:
- Caddy runs on the host
- The Portainer stack publishes container ports to localhost:
  - Frontend: `127.0.0.1:18080`
  - Backend: `127.0.0.1:18018`

```caddy
assistance.idc1.surf-thailand.com {
  # WebSocket endpoint to backend (do NOT strip; backend expects /ws/*)
  handle /jarvis/ws/* {
    reverse_proxy 127.0.0.1:18018
  }

  # Backend HTTP API (do NOT strip; backend expects /api/*)
  handle /jarvis/api/* {
    reverse_proxy 127.0.0.1:18018
  }

  # All other /jarvis paths go to the SPA frontend
  handle /jarvis/* {
    reverse_proxy 127.0.0.1:18080
  }
}
```

Notes:
- `handle` does not rewrite the request path.
- WebSockets work automatically through `reverse_proxy`.
