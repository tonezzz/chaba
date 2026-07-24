# Service catalog

| Service | Compose file | Ports | Purpose |
|---------|--------------|-------|---------|
| AI / 3DGS | `stacks/ai/docker-compose.yml` | 7007, 8888 | 3DGS research environment |
| NVR | `stacks/nvr/docker-compose.yml` | 5000, 8554, 8555 | Frigate NVR |
| Web | `stacks/web/docker-compose.yml` | 8080, 8090 | Caddy, status-api, camera-control, bserver |
| MCP | `mcp/server.py` | — | Planned read-only assistant interface |

## Common commands

```bash
make ai-up
make nvr-up
make web-up
make nvr-regenerate
make sync
```
