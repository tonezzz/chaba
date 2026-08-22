FROM node:22-alpine

# Used by the Quadlet health check.
RUN apk add --no-cache curl

# Build this image from the repo root so the COPY path resolves:
#   podman build -f stacks/web/rview-api/Dockerfile -t rview-api:latest .
WORKDIR /app
COPY stacks/web/rview-api/rview-api.mjs ./

EXPOSE 3007

ENV RVIEW_API_PORT=3007
ENV RVIEW_STATE_FILE=/data/state.json

CMD ["node", "rview-api.mjs"]
