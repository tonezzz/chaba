FROM ghcr.io/1mcp-app/agent:lite

WORKDIR /pipeline

COPY package.json /pipeline/package.json
COPY server.js /pipeline/server.js

RUN npm install --omit=dev

ENV ONE_MCP_HOST=0.0.0.0 \
    ONE_MCP_PORT=3050 \
    ONE_MCP_LOG_LEVEL=info \
    ONE_MCP_CONFIG_DIR=/pipeline/mcp-config \
    ONE_MCP_CONFIG=/pipeline/mcp-config/mcp.json

EXPOSE 3050

CMD ["sh", "-lc", "mkdir -p /pipeline/mcp-config && printf '%s' '{\"mcpServers\":{\"image-pipeline\":{\"command\":\"node\",\"args\":[\"/pipeline/server.js\"],\"tags\":[\"image\",\"pipeline\"],\"disabled\":false}}}' > /pipeline/mcp-config/mcp.json && exec node /usr/src/app/index.js"]
