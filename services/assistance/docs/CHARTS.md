
# Charts

These diagrams are the architecture blueprint for the `services/assistance` stack. Keep them accurate and update them whenever service boundaries, ports, endpoints, or persistence rules change.

## 1) System overview

```mermaid
flowchart LR
  U[User] <-->|WebSocket audio/text| FE[Jarvis Frontend]
  FE -->|WS /ws/live| BE[Jarvis Backend]

  BE -->|tools/call| MCP[mcp-bundle :3050]
  BE -->|memory read/write| WV[weaviate :8080]
  BE -->|writes/reads| DB[(jarvis_sessions.sqlite)]

  BE -->|jobs| DR[deep-research-worker :8030]
  DR -->|persists| DRDB[(deep_research.sqlite)]

  DB -->|due reminders| BE
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

## 3) Weaviate reminder fields

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
