FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# HTTP port for web UI and MCP SSE
EXPOSE 8080

CMD ["node", "index.js"]
