# Jarvis Assistance – Frontend/Backend Overview

Architecture of the **idc1-assistance** stack: browser UI, edge proxy, backend services, local state, and external APIs.

```mermaid
flowchart TD
    subgraph Client
        Browser((Browser))
    end

    subgraph Edge["Edge · Caddy (TLS + auth boundary)"]
        Caddy[Caddy\nreverse proxy]
    end

    subgraph AssistanceStack["Assistance Stack · idc1"]
        FE[jarvis-frontend\nstatic UI]
        BE[jarvis-backend\nHTTP + WebSocket]
        DRW[deep-research-worker\nasync HTTP]
        MCP[mcp-bundle\n1MCP gateway]
    end

    subgraph LocalState["Local State"]
        DB[(SQLite\nsessions · research)]
        WV[(Weaviate\nvector index)]
    end

    subgraph ExtAPIs["External APIs"]
        Gemini[Gemini API]
        Google[Google APIs\nTasks · Sheets · Calendar]
        GitHub[GitHub API]
    end

    Browser -->|HTTPS| Caddy
    Caddy -->|/jarvis/| FE
    Caddy -->|/jarvis/api/*| BE
    Caddy -->|/jarvis/ws/live| BE

    BE -->|HTTP| DRW
    BE -->|MCP protocol| MCP
    BE --> DB
    BE --> WV
    BE -->|LLM / live audio| Gemini

    DRW --> DB

    MCP --> Google
    MCP --> GitHub
```

**Legend**

| Node | Description |
|------|-------------|
| Caddy | Edge reverse proxy; terminates TLS and enforces the auth boundary |
| jarvis-frontend | Nginx-served static SPA (port 18080 inside stack) |
| jarvis-backend | Python service; HTTP REST + WebSocket live audio (port 18018) |
| deep-research-worker | Async HTTP worker called by backend (port 8030) |
| mcp-bundle | 1MCP gateway aggregating Google & GitHub MCP servers (port 3050) |
| SQLite | Session store (`JARVIS_SESSION_DB`) + research DB (`DEEP_RESEARCH_DB`) |
| Weaviate | Vector index for retrieval (`WEAVIATE_URL`) |
| Gemini API | Google Gemini – LLM inference and live audio (`GEMINI_API_KEY`) |
| Google APIs | Tasks, Sheets, Calendar via OAuth MCP tools |
| GitHub API | Repository access via `GITHUB_PERSONAL_TOKEN_RO/RW` |
