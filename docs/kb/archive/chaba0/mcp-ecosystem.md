---
kind: archive-report
bank: chaba-archive
source_repo: chaba0
source_commit: b5f1a6268e3e754a3281c55261a4ba7c8980bae9
topic: mcp-ecosystem
status: historical
period: [2025-12, 2026-03]
follows: []
superseded_by: current MCP servers (yomi, home-assistant, github, mddb, ...)
covers:
  - archive/mcp-glama-stdio/requirements.txt
  - archive/mcp-glama-stdio/server.py
  - devops-mcp.http
  - mcp/deka-chat-api/Dockerfile
  - mcp/deka-chat-api/main.py
  - mcp/deka-chat-api/requirements.txt
  - mcp/mcp-acc/Dockerfile
  - mcp/mcp-acc/main.py
  - mcp/mcp-acc/requirements.txt
  - mcp/mcp-agents/Dockerfile
  - mcp/mcp-agents/README.md
  - mcp/mcp-agents/index.js
  - mcp/mcp-agents/package-lock.json
  - mcp/mcp-agents/package.json
  - mcp/mcp-agents/www/test/agens/index.html
  - mcp/mcp-agents/www/test/agens/main.js
  - mcp/mcp-agents/www/test/agens/style.css
  - mcp/mcp-assistant/Dockerfile
  - mcp/mcp-assistant/main.py
  - mcp/mcp-assistant/requirements.txt
  - mcp/mcp-assistant/static/index.html
  - mcp/mcp-audidoc/Dockerfile
  - mcp/mcp-audidoc/main.py
  - mcp/mcp-audidoc/requirements.txt
  - mcp/mcp-cuda/Dockerfile
  - mcp/mcp-cuda/main.py
  - mcp/mcp-cuda/requirements.txt
  - mcp/mcp-deka/Dockerfile
  - mcp/mcp-deka/main.py
  - mcp/mcp-deka/requirements.txt
  - mcp/mcp-devops/.env.example
  - mcp/mcp-devops/Dockerfile
  - mcp/mcp-devops/README.md
  - mcp/mcp-devops/package-lock.json
  - mcp/mcp-devops/package.json
  - mcp/mcp-devops/scripts/diagnostics-dev-host.mjs
  - mcp/mcp-devops/scripts/diagnostics-dev-host.sh
  - mcp/mcp-devops/scripts/pc2-compose-control.mjs
  - mcp/mcp-devops/src/chatAgent.js
  - mcp/mcp-devops/src/chatStore.js
  - mcp/mcp-devops/src/config.js
  - mcp/mcp-devops/src/executors.js
  - mcp/mcp-devops/src/index.js
  - mcp/mcp-devops/src/llmClient.js
  - mcp/mcp-devops/src/mcp0Client.js
  - mcp/mcp-devops/src/runStore.js
  - mcp/mcp-devops/src/telemetry.js
  - mcp/mcp-devops/src/workflowCatalog.js
  - mcp/mcp-doc-archiver/.dockerignore
  - mcp/mcp-doc-archiver/Dockerfile
  - mcp/mcp-doc-archiver/README.md
  - mcp/mcp-doc-archiver/main.py
  - mcp/mcp-doc-archiver/requirements.txt
  - mcp/mcp-docker/.dockerignore
  - mcp/mcp-docker/.gitignore
  - mcp/mcp-docker/.python-version
  - mcp/mcp-docker/Dockerfile
  - mcp/mcp-docker/LICENSE
  - mcp/mcp-docker/README.md
  - mcp/mcp-docker/pyproject.toml
  - mcp/mcp-docker/src/docker_mcp/__init__.py
  - mcp/mcp-docker/src/docker_mcp/docker_executor.py
  - mcp/mcp-docker/src/docker_mcp/handlers.py
  - mcp/mcp-docker/src/docker_mcp/http_server.py
  - mcp/mcp-docker/src/docker_mcp/server.py
  - mcp/mcp-docker/uv.lock
  - mcp/mcp-github-models/Dockerfile
  - mcp/mcp-github-models/main.py
  - mcp/mcp-github-models/requirements.txt
  - mcp/mcp-glama/Dockerfile
  - mcp/mcp-glama/main.py
  - mcp/mcp-glama/requirements.txt
  - mcp/mcp-http/.dockerignore
  - mcp/mcp-http/Dockerfile
  - mcp/mcp-http/main.py
  - mcp/mcp-http/requirements.txt
  - mcp/mcp-imagen/Dockerfile
  - mcp/mcp-imagen/main.py
  - mcp/mcp-imagen/requirements.txt
  - mcp/mcp-imagen-light/Dockerfile
  - ... (91 more files under topic)
extracted: 2026-09-24
extracted_by: gemini-2.5-flash (benchmark)
---

# Mcp Ecosystem — archive of chaba0

## Summary
The `mcp-ecosystem` comprised a collection of microservices built around the Model Context Protocol (MCP) within the `chaba0` project. These services, typically named `mcp-<function>`, exposed various functionalities as structured tools, enabling AI assistants like Claude Desktop to interact with external systems and data sources. It formed the modular backbone for `chaba0`'s capabilities, encompassing components for RAG, image generation, DevOps, Docker management, chat, and observability.

## Timeline
dates unknown — frozen 2026-03-28

## Still-true facts
*   The Model Context Protocol (MCP) was a core architectural principle. [still-true]
*   Services were primarily implemented in Python (FastAPI) and Node.js (Express). [still-true]
*   Many services were designed to expose structured tools for AI agents. [still-true]
*   `chaba0` was an early AI-assistant platform. [historical]
*   Claude Desktop was an intended client for MCP services. [historical]
*   `mcp-glama` and `mcp-openai-gateway` acted as interfaces to LLM backends. [still-true]
*   `mcp-rag` provided Retrieval Augmented Generation capabilities. [still-true]
*   `mcp-cuda` and `mcp-imagen` handled GPU-accelerated tasks like image generation and embeddings. [still-true]
*   `mcp-docker` enabled AI control over Docker operations. [still-true]
*   `mcp-tester` was used for health checks and validation of the stack. [still-true]
*   `mcp-task` was a minimal orchestrator for tool invocation. [still-true]
*   `mcp-assistant` was an endpoint for tool invocation, acting as a central router. [still-true]
*   `mcp-http` provided a controlled way for agents to make HTTP requests. [still-true]
*   `mcp-webtops` managed ephemeral browser environments. [still-true]
*   `mcp-doc-archiver` and `mcp-audidoc` handled document processing and archiving. [still-true]
*   `mcp-deka` was a web scraping/automation service, often paired with Playwright. [still-true]
*   `mcp-meeting` likely handled meeting-related functionalities. [still-true]
*   `mcp-quickchart` generated charts. [still-true]
*   `mcp-memory` was a Node.js service, likely for persistent memory/state. [still-true]
*   `mcp-ws-gateway` bridged WebSocket clients to SSE and MCP JSON-RPC. [still-true]
*   `mcp-devops` aimed to automate preview and publish workflows. [historical]
*   `mcp-agents` provided observability into multi-agent API sessions. [historical]
*   `mcp-line` integrated with the LINE messaging platform. [historical]

## Key details
The `mcp-ecosystem` was a modular architecture where each `mcp-<service>` was a microservice exposing specific capabilities via the Model Context Protocol (MCP). These services typically ran as FastAPI (Python) or Express (Node.js) applications, communicating via HTTP.

**Core Components and their functions:**
*   **`mcp0`**: The central MCP router/gateway, responsible for discovering and routing requests to other MCP providers using a `ProviderRegistry`.
*   **`deka-chat-api`**: A chat API integrating RAG and LLM services, leveraging `mcp-rag-deka`, `mcp-glama`, and `mcp-deka`.
*   **`mcp-acc`**: A web content processing and automation service, using `BeautifulSoup` and `httpx` for accessing and manipulating web resources.
*   **`mcp-agents`**: Provided observability tools for multi-agent API sessions, allowing clients to `fetch_sessions`, `fetch_archives`, and perform `observability_probe` checks against an `AGENTS_API_BASE`.
*   **`mcp-assistant`**: An endpoint for tool invocation, acting as a proxy or orchestrator, connecting to an LLM (`GLAMA_MCP_URL`) and a general tool invocation endpoint (`ONE_MCP_URL`).
*   **`mcp-audidoc`**: Handled document processing, including PDF parsing (`PyPDF`) and potentially OCR (`pytesseract`).
*   **`mcp-cuda`**: A GPU-accelerated service for tasks like image generation (`StableDiffusionPipeline`) and embeddings (`SentenceTransformer`, `CrossEncoder`).
*   **`mcp-deka`**: A web scraping and automation service, often integrating with `mcp-playwright` for browser automation, storing data in SQLite.
*   **`mcp-devops`**: Automated `chaba0`'s preview and publish workflows, exposing tools for `preview automation` and `publish orchestration` by wrapping existing scripts.
*   **`mcp-doc-archiver`**: A document archiving and chat UI service, built on `mcp-rag` and `mcp-openai-gateway`, supporting PDF uploads and OCR.
*   **`mcp-docker`**: Enabled AI agents to manage Docker containers and Compose stacks, offering features like creation, deployment, logging, and status monitoring.
*   **`mcp-github-models`**: An interface to GitHub-hosted LLM models.
*   **`mcp-glama`**: A generic LLM gateway, routing requests to a configured `GLAMA_API_URL`.
*   **`mcp-http`**: A controlled HTTP client for agents, allowing them to make web requests within defined `ALLOWED_HOSTS`.
*   **`mcp-imagen`**: An image generation service using `diffusers` (e.g., `StableDiffusion`) for text-to-image tasks.
*   **`mcp-imagen-light`**: A lighter image generation service, likely offloading heavy processing to `mcp-cuda` and managing image storage.
*   **`mcp-instrans`**: (Node.js) A translation service, likely using Google Translate API.
*   **`mcp-line`**: An integration with the LINE messaging platform.
*   **`mcp-meeting`**: A service for managing meeting-related functionalities.
*   **`mcp-memory`**: (Node.js) A service for persistent memory or state management.
*   **`mcp-openai-gateway`**: An OpenAI-compatible API gateway, routing requests to `GLAMA_API_URL` or `MCP_AGENT_URL`.
*   **`mcp-quickchart`**: Generated charts using the QuickChart API.
*   **`mcp-rag`**: A Retrieval Augmented Generation service, using `QdrantClient` for vector search (text and image collections) and `SentenceTransformer` for embeddings, potentially with `Ollama`.
*   **`mcp-rag-light`**: A lighter RAG service, potentially offloading embeddings to `mcp-cuda`.
*   **`mcp-task`**: A minimal task orchestrator, persisting tasks to SQLite and supporting tool calls on other MCP providers.
*   **`mcp-tester`**: A health check service for the `chaba0` stack, running declarative HTTP tests and providing structured pass/fail summaries.
*   **`mcp-vaja`**: (Node.js) Functionality uncertain, but `vaja` often implies voice/audio processing.
*   **`mcp-webtops`**: Managed ephemeral browser environments (Docker-based) for agents.
*   **`mcp-ws-gateway`**: A WebSocket gateway, bridging browser clients to `mcp-openai-gateway` (SSE) and `1mcp-agent` (MCP JSON-RPC).
*   **`webtops-cp`**: A control panel for `mcp-webtops`.
*   **`webtops-router`**: A router for `webtops`, managing connections and state for ephemeral browser environments.

**Survival into `chaba`/`ada-pi`:**
The core concept of modular, MCP-based services for AI tools was preserved and evolved. Fundamental capabilities like LLM gateways, RAG, image generation/processing, web automation, tool orchestration, task management, document processing, and observability/testing were critical and carried over, likely refactored and integrated more deeply into the successor platform's architecture. Specific implementations and legacy dependencies were updated or replaced.

## Not preserved
*   **Specific `chaba0` deployment scripts and targets within `mcp-devops`**: The direct wrappers around `chaba0`-era PowerShell and shell scripts (e.g., `deploy-a1-idc1.sh`) were not preserved. This was because `chaba`/`ada-pi` developed its own, more integrated and robust CI/CD and deployment pipelines, rendering the `chaba0`-specific automation obsolete.
*   **The `mcp-line` messaging integration as a standalone service**: This specific integration with the LINE platform was likely not preserved in its original form. Future platforms would either integrate messaging capabilities more generically or focus on core AI functionalities, leaving specific platform integrations to more flexible, configurable adapters or third-party tools.
*   **The `mcp-agents` direct proxy to `sites/a1-idc1/api/agents`**: This component's direct dependency on a `chaba0`-specific multi-agent API endpoint was not preserved. `chaba`/`ada-pi` would have developed its own internal agent management and observability APIs, making this specific proxy redundant.
*   **The `mcp0` codebase as a standalone router**: While the *functionality* of a central MCP router and tool registry was critical and evolved into the core of `chaba`/`ada-pi`'s agent runtime, the specific `mcp0` implementation was likely refactored and integrated more deeply into the successor platform's architecture for improved performance, scalability, and tighter coupling with the new system.

## Source map

- `mcp/ except mcp-playwright` → report sections above (bundle: file headers/READMEs/first-60-lines per file, 171 files)
