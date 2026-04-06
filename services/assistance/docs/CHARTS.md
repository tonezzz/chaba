
# Charts

These diagrams are the architecture blueprint for the `services/assistance` stack. Keep them accurate and update them whenever service boundaries, ports, endpoints, or persistence rules change.

## Pointers (SSOT)

- Operator runbooks (SSOT): `services/assistance/docs/ACTION.md`
- Assistance overview: `services/assistance/README.md`
- Runtime API surface (authoritative): `GET /openapi.json`

## CI: sheet contract tests

We run a lightweight `pytest` suite in CI to prevent regressions in the Google Sheets SSoT contracts (system/memory/knowledge KV5 parsing and memo header canonicalization).

- Workflow: `.github/workflows/tests-idc1-assistance.yml`
- Test location: `services/assistance/jarvis-backend/test_*.py` (notably `test_sheet_contracts.py`)

Run locally:

```bash
cd services/assistance/jarvis-backend
pip install -r requirements.txt
pytest -q
```

## 0) Google Sheets SSoT (sys/memory/knowledge/notes/gems)

```mermaid
flowchart LR
  U[User]
  FE[Jarvis Frontend]
  BE[Jarvis Backend]
  GDMCP[google-drive-mcp :8032]

  subgraph GSS[Google Sheets (Authoritative SSoT)]
    SYS[sys\n(key/value/enabled/scope/priority)]
    MEM[memory\n(key/value/enabled/scope/priority)]
    KNOW[knowledge\n(key/value/enabled/scope/priority)]
    NOTES[notes.0\n(id/date_time/subject/notes/status/time)]
    GEMS[gems\n(id/name/purpose/persona/model/...) ]
  end

  subgraph BEState[Backend state (derived + cached)]
    SYSKV[ws.state.sys_kv]
    MEMITEMS[ws.state.memory_items]
    KNOWITEMS[ws.state.knowledge_items]
    MEMCTX[memory_context_text\n(injected to Gemini)]
    KNOWCTX[knowledge_context_text\n(injected to Gemini)]
    GEMCACHE[gems cache\n(sheet-driven gem selection)]
  end

  U <-->|WebSocket audio/text| FE
  FE -->|/jarvis/ws/live| BE

  BE -->|tools/call (MCP-over-HTTP)| GDMCP
  GDMCP -->|getGoogleSheetContent| SYS
  GDMCP -->|getGoogleSheetContent| MEM
  GDMCP -->|getGoogleSheetContent| KNOW
  GDMCP -->|appendSpreadsheetRows / updateGoogleSheet| NOTES
  GDMCP -->|getGoogleSheetContent| GEMS

  SYS -->|pointers: notes_ss/notes_sh, memory.sheet_name, knowledge.sheet_name, gems_*| BE
  BE --> SYSKV
  BE --> MEMITEMS
  BE --> KNOWITEMS
  MEMITEMS --> MEMCTX
  KNOWITEMS --> KNOWCTX
  GEMS --> GEMCACHE

  KNOWITEMS -.->|dedupe by key| MEMITEMS
```

## 6.6) Deterministic WS tools (per-tool charts)

These are the Mode B control-plane tools that are handled purely by the backend and never forwarded to Gemini.

### 6.6.1) system.reload

```mermaid
flowchart LR
  FE[Jarvis Frontend] -->|{"type":"system","action":"reload","mode":...}| BE[Jarvis Backend]
  BE -->|text/progress| FE
  BE -->|error(kind=invalid_reload_mode/reload_failed)| FE
```

### 6.6.2) notes.*

```mermaid
flowchart LR
  FE[Jarvis Frontend] -->|{"type":"notes","action":"check"}| BE[Jarvis Backend]
  BE -->|text summary + Next:| FE
  FE -->|{"type":"notes","action":"next"}| BE
  BE -->|text next-step line| FE
  FE -->|{"type":"notes","action":"add","text":"..."}| BE
  BE -->|note_created / note_prompt| FE
```

### 6.6.4) gems.*

```mermaid
flowchart LR
  FE[Jarvis Frontend] -->|{"type":"gems","action":"list"}| BE[Jarvis Backend]
  BE -->|gems_list| FE
  FE -->|{"type":"gems","action":"upsert","gem":{...}}| BE
  BE -->|gems_upserted| FE
  FE -->|{"type":"gems","action":"remove","gem_id":"..."}| BE
  BE -->|gems_removed| FE

  FE -->|{"type":"gems","action":"analyze","gem_id":"...","criteria":"..."}| BE
  BE -->|gems_draft_created (draft_id, before/after, changed)| FE
  FE -->|{"type":"gems","action":"draft_apply","draft_id":"..."}| BE
  BE -->|gems_draft_applied| FE
  FE -->|{"type":"gems","action":"draft_discard","draft_id":"..."}| BE
  BE -->|gems_draft_discarded| FE
```

## 6.5) Frontend smart mapping (typed + voice)

```mermaid
flowchart LR
  U[User]
  FE[Jarvis Frontend]
  BE[Jarvis Backend]
  GL[Gemini Live]

  U -->|typed composer| FE
  U -->|voice| GL
  GL -->|transcript source=input| FE

  FE -->|match => WS tools
  system.* / notes.* / gems.*| BE
  FE -->|no match => WS text| BE
  BE -->|forward text/audio| GL
```

## 1) System overview

```mermaid
flowchart LR
  U[User] <-->|WebSocket audio/text| FE[Jarvis Frontend]
  FE -->|WS /jarvis/ws/live| BE[Jarvis Backend]

  BE -->|tools/call (MCP-over-HTTP)| GDMCP[google-drive-mcp :8032]
  BE -->|tools/call (MCP JSON-RPC)| MCP[mcp-bundle :3050]
  BE -->|memory read/write| WV[weaviate :8080]
  BE -->|writes/reads| DB[(jarvis_sessions.sqlite)]

  BE -->|jobs| DR[deep-research-worker :8030]
  DR -->|persists| DRDB[(deep_research.sqlite)]
  BE -->|structured events| FE
```

## 2) MCP bundle (gateway)

```mermaid
flowchart LR
  MCP[mcp-bundle :3050]

  subgraph MCP_bundle["mcp-bundle (MCP gateway)"]
    MCPF[fetch]
    MCPP[playwright]
    MCPS[server-sequential-thinking]
  end

  MCP --> MCPF
  MCP --> MCPP
  MCP --> MCPS
```

## 3) Weaviate fields

```mermaid
flowchart TB
  subgraph WEAVIATE["Weaviate (vector DB)"]
    WVC[JarvisMemoryItem]
    WVK[external_key]
    WVKind[kind]
    WVTitle[title]
    WVStatus[status]
    WVDue[due_at]
    WVNotify[notify_at]
    WVHide[hide_until]
  end

  WVC --> WVK
  WVC --> WVKind
  WVC --> WVTitle
  WVC --> WVStatus
  WVC --> WVDue
  WVC --> WVNotify
  WVC --> WVHide
```

## 4) Cars (planned)

```mermaid
flowchart LR
  FE[Jarvis Frontend] -->|image upload| BE[Jarvis Backend]
  BE -->|stores assets/data| FS[(assistance_data bind mount)]
  FS -->|cars dataset| CARS[assistance_data/cars]
  CARS -->|originals| ORIG[originals/]
  CARS -->|plates| PLATES[plates/]
  CARS -->|car crops| CROPS[cars/]
```

## 7) WebSocket contract (high-level)

```mermaid
flowchart TB
  subgraph Inbound[Client -> Backend (/jarvis/ws/live)]
    IN_TEXT["text: {text}"]
    IN_AUDIO["audio: {data,sampleRate}"]
    IN_CLOSE["close"]
    IN_SYSTEM["system: {action,mode}"]
    IN_NOTES["notes: {action,text}"]
    IN_GEMS["gems: {action,...}"]
  end

  subgraph Outbound[Backend -> Client (/jarvis/ws/live)]
    OUT_STATE["state: connected"]
    OUT_ERR["error: gemini_* or other"]
    OUT_TR_IN["transcript (input)"]
    OUT_TR_OUT["transcript (output)"]
    OUT_TXT["text"]
    OUT_AUDIO["audio"]
    OUT_GEMS["gems_list / gems_upserted / gems_removed"]
    OUT_NOTES["note_created / note_prompt"]
  end
```

## 8) Deploy / runtime boundaries

```mermaid
flowchart LR
  U[User Browser]
  PUB[Public HTTPS Ingress]
  FE[Jarvis Frontend (/jarvis/)]
  BE[Jarvis Backend (:8018)]
  GDMCP[google-drive-mcp :8032]

  subgraph DockerNet[Docker network: idc1-stack-net]
    MCP[mcp-bundle :3050]
    WV[weaviate :8080]
    DR[deep-research-worker :8030]
  end

  U -->|https://.../jarvis/| PUB
  PUB --> FE
  FE -->|wss /jarvis/ws/live| BE

  BE --> MCP
  BE --> GDMCP
  BE --> WV
  BE --> DR
```

## 9) Folder overview (where things live)

```mermaid
flowchart TB
  ROOT[/repo root/]

  ROOT --> SA[services/assistance/]
  ROOT --> ST[stacks/idc1-assistance/]

  SA --> JB[jarvis-backend/]
  SA --> JF[jarvis-frontend/]
  SA --> DRW[deep-research-worker/]
  SA --> MCP[mcp-servers/]
  SA --> TRIP[trip/]
  SA --> DOCS[docs/]

  JB --> JB_AGENTS[agents/*.md]
  JB --> JB_MAIN[main.py]

  DOCS --> DOCS_BUILD[BUILD.md]
  DOCS --> DOCS_CHARTS[CHARTS.md]

  ST --> ST_COMPOSE[docker-compose.yml]
  ST --> ST_CFG[mcp-config/]
```
