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

CMD ["sh", "-c", "set -e\nmkdir -p /pipeline/mcp-config\ncat > /pipeline/mcp-config/mcp.json <<'EOF'\n{\"mcpServers\":{\"image-pipeline\":{\"command\":\"node\",\"args\":[\"/pipeline/server.js\"],\"tags\":[\"image\",\"pipeline\"],\"disabled\":false,\"env\":{\"GEMINI_API_KEY\":\"${GEMINI_API_KEY}\",\"API_KEY\":\"${GEMINI_API_KEY}\"}}}}\nEOF\nexec node /usr/src/app/index.js\n"]
