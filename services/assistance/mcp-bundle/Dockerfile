FROM ghcr.io/1mcp-app/agent:lite

RUN apk add --no-cache python3 py3-pip ca-certificates curl \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir mcp-server-fetch

COPY ./entrypoint.sh /app/entrypoint.sh
COPY ./proxy.js /app/proxy.js
COPY ./mcp-config/mcp.json /app/mcp-config/mcp.json

RUN chmod +x /app/entrypoint.sh

ENV PATH="/opt/venv/bin:${PATH}"

ENTRYPOINT ["/app/entrypoint.sh"]
