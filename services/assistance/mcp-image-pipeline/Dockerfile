FROM ghcr.io/1mcp-app/agent:lite

WORKDIR /app

COPY package.json /app/package.json
COPY server.js /app/server.js

RUN npm install --omit=dev

ENV ONE_MCP_HOST=0.0.0.0 \
    ONE_MCP_PORT=3050 \
    ONE_MCP_LOG_LEVEL=info \
    ONE_MCP_CONFIG_DIR=/app/mcp-config \
    ONE_MCP_CONFIG=/app/mcp-config/mcp.json

EXPOSE 3050

CMD ["sh", "-lc", "mkdir -p /app/mcp-config && printf '%s' '{\"mcpServers\":{\"image-pipeline\":{\"command\":\"node\",\"args\":[\"/app/server.js\"],\"tags\":[\"image\",\"pipeline\"],\"disabled\":false}}}' > /app/mcp-config/mcp.json && exec node index.js"]
