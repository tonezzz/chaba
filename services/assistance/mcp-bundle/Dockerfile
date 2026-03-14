FROM ghcr.io/1mcp-app/agent:lite

RUN apk add --no-cache python3 py3-pip ca-certificates curl \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir mcp-server-fetch

COPY ./mcp-servers/mcp-google-sheets/server.js /app/mcp-servers/mcp-google-sheets/server.js

ENV PATH="/opt/venv/bin:${PATH}"
