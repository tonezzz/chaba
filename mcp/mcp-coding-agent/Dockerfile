# syntax=docker/dockerfile:1.7

FROM node:20-bookworm-slim AS base

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src

ENV NODE_ENV=production \
    MCP_CODING_AGENT_PORT=8350 \
    MCP_CODING_AGENT_HOST=0.0.0.0

EXPOSE 8350

CMD ["npm", "start"]
