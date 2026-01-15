# syntax=docker/dockerfile:1.7
ARG NODE_VERSION=20.18.0
FROM node:${NODE_VERSION}-bookworm-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY package*.json ./
RUN npm ci --omit=dev

COPY src ./src
COPY public ./public

ENV NODE_ENV=production \
    PORT=3100

EXPOSE 3100
CMD ["node", "src/index.js"]
