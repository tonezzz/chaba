FROM node:22-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev

COPY server.mjs ./

EXPOSE 3002

ENV GEMINI_LIVE_PORT=3002
ENV RVIEW_API_URL=http://rview-api:3007/state.php

CMD ["node", "server.mjs"]
