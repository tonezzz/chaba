# syntax=docker/dockerfile:1.7

FROM node:20-bookworm-slim AS base

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      curl \
      gnupg \
      openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI + docker compose plugin (v2) from Debian repositories.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Install PowerShell (pwsh) for running PowerShell-based workflows inside the container.
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends powershell \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src

ENV NODE_ENV=production \
    MCP_DEVOPS_PORT=8325 \
    MCP_DEVOPS_HOST=0.0.0.0

EXPOSE 8325

CMD ["npm", "start"]
