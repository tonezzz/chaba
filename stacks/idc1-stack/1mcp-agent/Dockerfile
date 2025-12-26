FROM python:3.12-slim-bookworm

RUN apt-get update \
  && apt-get install -y --no-install-recommends bash ca-certificates curl gnupg \
  && install -m 0755 -d /etc/apt/keyrings \
  && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
  && chmod a+r /etc/apt/keyrings/docker.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
  && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 (required for @1mcp/agent)
RUN mkdir -p /etc/apt/keyrings \
  && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
  && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

COPY mcp-tasks/stacks/idc1-stack/1mcp-agent/docker-mcp-stdio.sh /usr/local/bin/docker-mcp-stdio
RUN chmod +x /usr/local/bin/docker-mcp-stdio

RUN npm install -g corepack && corepack enable

# Build 1MCP from local source (requires docker-compose build.context = C:\chaba_wt)
COPY voyant/1mcp-agent-src /opt/1mcp-agent-src
WORKDIR /opt/1mcp-agent-src
RUN pnpm install --frozen-lockfile --prefer-offline
RUN sed -i 's/\r$//' ./scripts/build.sh && bash ./scripts/build.sh

CMD ["node", "build/index.js"]
