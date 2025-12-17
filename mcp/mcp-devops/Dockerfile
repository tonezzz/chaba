# syntax=docker/dockerfile:1.7

FROM node:20-alpine AS base

WORKDIR /app

RUN apk add --no-cache bash docker-cli docker-cli-compose

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY src ./src

ENV NODE_ENV=production \
    MCP_DEVOPS_PORT=8325 \
    MCP_DEVOPS_HOST=0.0.0.0

EXPOSE 8325

CMD ["npm", "start"]
