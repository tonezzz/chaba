FROM node:22-alpine

# mcp_rview/server.py runs under Python 3; curl is used by the Quadlet health check.
RUN apk add --no-cache python3 curl

# Build this image from the repo root so the COPY paths below resolve:
#   podman build -f stacks/web/rview-live/Dockerfile -t rview-live:latest .
# Override the listen port when building for tony-dell:
#   podman build --build-arg GEMINI_LIVE_PORT=3008 -f stacks/web/rview-live/Dockerfile -t rview-live:latest .
ARG GEMINI_LIVE_PORT=3002
WORKDIR /app
COPY stacks/web/rview-live/package*.json ./
RUN npm ci --omit=dev
COPY stacks/web/rview-live/server.mjs ./
COPY stacks/web/rview-live/search.mjs ./
COPY scripts/mcp_rview /scripts/mcp_rview

EXPOSE ${GEMINI_LIVE_PORT}

ENV GEMINI_LIVE_PORT=${GEMINI_LIVE_PORT}
ENV GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview
ENV RVIEW_API_URL=http://rview-api:3007/state

CMD ["node", "server.mjs"]
