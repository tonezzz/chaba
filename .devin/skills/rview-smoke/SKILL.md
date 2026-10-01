---
name: rview-smoke
description: End-to-end smoke testing for the RView API, MCP server, and static UI.
---

# RView smoke testing

## What this covers

- `stacks/web/rview-api/rview-api.mjs` Node HTTP service
- `scripts/mcp_rview/server.py` stdio MCP server + `scripts/mcp_rview/views.py` HTTP client
- `stacks/web/public/apps/rview/index.html` static viewer UI

## Devin Secrets Needed

- None for local rview smoke tests.

## Prerequisites

- Node.js (tested with v20.18.1) and Python 3 (tested with 3.10.12).
- Pillow installed if you want to generate a local sample image:
  `python3 -c "from PIL import Image"` should succeed.
- `stacks/web/rview-api/rview-api.mjs` must be runnable with `node`.

## One-shot syntax checks

```bash
node --check stacks/web/rview-api/rview-api.mjs
python3 -m py_compile scripts/mcp_rview/server.py scripts/mcp_rview/views.py
```

## Start the rview API locally

```bash
export RVIEW_STATE_FILE=/tmp/rview-state.json
node stacks/web/rview-api/rview-api.mjs &
```

The API listens on `RVIEW_API_PORT` (default `3007`) and persists state to the file above.

## API curl smoke test

All requests hit `http://localhost:3007/state.php`:

```bash
curl -s 'http://localhost:3007/state.php?action=list'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"create","view_id":"smoke","display_name":"Smoke Test"}' 'http://localhost:3007/state.php'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"show","view_id":"smoke","url":"http://localhost:8090/sample.png","title":"Sample","media_type":"image"}' 'http://localhost:3007/state.php'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"queue","view_id":"smoke","items":[{"url":"http://localhost:8090/sample.png","title":"Q1"},{"url":"http://localhost:8090/sample.png","title":"Q2"}],"mode":"append"}' 'http://localhost:3007/state.php'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"control","view_id":"smoke","command":"next"}' 'http://localhost:3007/state.php'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"control","view_id":"smoke","command":"pause"}' 'http://localhost:3007/state.php'
curl -s 'http://localhost:3007/state.php?action=status&view_id=smoke'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"delete","view_id":"smoke"}' 'http://localhost:3007/state.php'
```

Expect every response to contain `"ok": true`.

## MCP stdio JSON-RPC smoke test

```bash
RVIEW_API_URL=http://localhost:3007/state.php python3 scripts/mcp_rview/server.py
```

Feed newline-delimited JSON-RPC. Tool names are `rview_create_view`, `rview_show`, `rview_queue`, `rview_control`, `rview_status`, `rview_list_views`, `rview_delete_view`.

```json
{"jsonrpc":"2.0","id":1,"method":"initialize"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"rview_create_view","arguments":{"view_id":"mcp","display_name":"MCP Smoke"}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"rview_show","arguments":{"view_id":"mcp","url":"http://localhost:8090/sample.png","title":"MCP Sample","media_type":"image"}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"rview_queue","arguments":{"view_id":"mcp","items":[{"url":"http://localhost:8090/sample.png","title":"Q1"},{"url":"http://localhost:8090/sample.png","title":"Q2"}],"mode":"append"}}}
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"rview_control","arguments":{"view_id":"mcp","action":"next"}}}
{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"rview_status","arguments":{"view_id":"mcp"}}}
{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"rview_list_views","arguments":{}}}
{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"rview_delete_view","arguments":{"view_id":"mcp"}}}
```

## Static UI test

The UI at `stacks/web/public/apps/rview/index.html` expects to be served under `/apps/rview/` and polls `/apps/rview/api/state.php`.
In production Caddy does this; for local smoke testing you can use a small Node reverse proxy.

Generate a local sample PNG first:

```bash
cat > /tmp/rview-sample.png.py << 'PY'
from PIL import Image, ImageDraw, ImageFont
img = Image.new('RGB', (300, 200), color='red')
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 32)
except Exception:
    font = ImageFont.load_default()
draw.text((20, 80), 'RView smoke test', fill='white', font=font)
img.save('/tmp/rview-sample.png')
PY
python3 /tmp/rview-sample.png.py
```

Then serve the UI and proxy API requests (this example also sets `Cache-Control: no-store` because `rview-api.mjs` does not currently emit cache headers, and Chrome may cache the `status` GET otherwise):

```js
import { createServer, request as httpRequest } from 'http';
import { readFileSync } from 'fs';
import { URL } from 'url';

const PORT = 8090;
const API_HOST = 'localhost';
const API_PORT = 3007;
const INDEX_HTML = '/home/ubuntu/repos/chaba/stacks/web/public/apps/rview/index.html';
const SAMPLE_PNG = '/tmp/rview-sample.png';

function proxyToApi(req, res, targetPath, search) {
  const options = { hostname: API_HOST, port: API_PORT, path: targetPath + (search || ''), method: req.method, headers: { 'Content-Type': req.headers['content-type'] || 'application/json' } };
  const proxyReq = httpRequest(options, (proxyRes) => {
    const headers = { ...proxyRes.headers };
    headers['cache-control'] = 'no-store, no-cache, must-revalidate, proxy-revalidate';
    headers['pragma'] = 'no-cache';
    res.writeHead(proxyRes.statusCode, headers);
    proxyRes.pipe(res);
  });
  proxyReq.on('error', (err) => { res.writeHead(502); res.end(JSON.stringify({ ok: false, error: String(err) })); });
  req.pipe(proxyReq);
}

createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (url.pathname === '/apps/rview' || url.pathname === '/apps/rview/' || url.pathname === '/apps/rview/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(readFileSync(INDEX_HTML));
    return;
  }
  if (url.pathname === '/sample.png') {
    res.writeHead(200, { 'Content-Type': 'image/png' });
    res.end(readFileSync(SAMPLE_PNG));
    return;
  }
  if (url.pathname === '/apps/rview/api/state.php') {
    proxyToApi(req, res, '/state.php', url.search);
    return;
  }
  res.writeHead(404); res.end('not found');
}).listen(PORT, () => console.log(`rview UI proxy listening on http://localhost:${PORT}`));
```

Pre-populate a view:

```bash
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"create","view_id":"uitest","display_name":"UI Smoke"}' 'http://localhost:3007/state.php'
curl -s -X POST -H 'Content-Type: application/json' -d '{"action":"show","view_id":"uitest","url":"http://localhost:8090/sample.png","title":"UI Smoke","media_type":"image"}' 'http://localhost:3007/state.php'
```

Open `http://localhost:8090/apps/rview/index.html` in Chrome. Verify:
- the stage renders an `<img>` with the sample image,
- the status text reads `playing | image | UI Smoke`,
- the Playback controls (pause, play, next) update the status text and queue list.

## Known testing gotchas

- `rview-api.mjs` does not set `Cache-Control` headers on `GET /state.php`. If the UI appears stale while manually clicking controls, run the API behind a reverse proxy that adds `Cache-Control: no-store`, or disable the browser cache while testing.
- The sample image must be on the same origin/port as the UI so the `<img src>` loads without mixed-content or CORS issues.
- The MCP server uses `RVIEW_API_URL` to reach the API; override it to `http://localhost:3007/state.php` when running locally.
