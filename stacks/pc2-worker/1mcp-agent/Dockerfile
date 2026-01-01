FROM node:22-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates curl docker.io python3 python3-venv \
  && rm -rf /var/lib/apt/lists/*

RUN npm install -g @1mcp/agent

COPY docker-mcp-stdio.sh /usr/local/bin/docker-mcp-stdio
RUN chmod +x /usr/local/bin/docker-mcp-stdio

WORKDIR /app

CMD ["1mcp"]
