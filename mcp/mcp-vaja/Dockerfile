FROM node:20-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

COPY shared ./shared
COPY mcp_vaja ./mcp_vaja

WORKDIR /app/mcp_vaja
RUN npm install --production

ENV PORT=8017
EXPOSE 8017

CMD ["npm", "start"]
