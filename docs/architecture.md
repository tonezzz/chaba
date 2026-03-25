# Chaba Frontend–Backend Architecture

This diagram provides a high-level overview of how the Chaba frontend and backend components interact.

```mermaid
graph TD
  subgraph Frontend
    UI[Static UI\nHTML / CSS / JS]
  end

  subgraph Backend["Backend (Node.js / Express)"]
    Server[site-chat Server\nport 3020]
    Health[GET /api/health]
    Chat[POST /api/chat]
    Static[Static File Serving\n/public]
  end

  subgraph External
    Glama[Glama LLM API\nOpenAI-compatible]
  end

  UI -->|"POST /api/chat\n{ message, history }"| Chat
  UI -->|"GET /api/health"| Health
  UI -->|"Static assets"| Static

  Chat -->|"Bearer token + messages"| Glama
  Glama -->|"Chat completion response"| Chat
  Chat -->|"{ reply, usage }"| UI
  Health -->|"{ status, model, timestamp }"| UI
```

## Component Notes

| Component | Description |
|-----------|-------------|
| **Static UI** | Plain HTML/CSS/JS served from `public/`; sends user messages and conversation history to the backend |
| **site-chat Server** | Express app that validates requests, manages conversation context, and proxies LLM calls |
| **`GET /api/health`** | Returns readiness status and the active model name |
| **`POST /api/chat`** | Accepts a user message + optional history, forwards to Glama, returns the assistant reply |
| **Glama LLM API** | OpenAI-compatible external API used for chat completions; authenticated via `GLAMA_API_KEY` |
