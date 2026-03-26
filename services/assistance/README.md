# assistance

Jarvis assistance service: voice/chat frontend (`jarvis-frontend`) and AI backend (`jarvis-backend`).

## Start here

| Goal | Doc |
|------|-----|
| Deploy / operate | [`docs/ACTION.md`](docs/ACTION.md) |
| Architecture diagrams | [`docs/CHARTS.md`](docs/CHARTS.md) |
| Stack config (compose + env) | [`../../stacks/idc1-assistance/`](../../stacks/idc1-assistance/) |
| Infrastructure overview | [`../../docs/stacks.md`](../../docs/stacks.md) |
| Full API reference | `GET /openapi.json` on the running backend |

## Key URLs (idc1 deployment)

- Frontend: `http://127.0.0.1:18080/jarvis/`
- Backend health: `http://127.0.0.1:18018/health`
- Backend API spec: `http://127.0.0.1:18018/openapi.json`
