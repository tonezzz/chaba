FROM node:20-alpine

WORKDIR /app

# Install dependencies
COPY package.json ./
RUN npm install

# Copy source
COPY . .

# Data volume for SQLite
VOLUME ["/data"]

# HTTP port for web UI
EXPOSE 8080

CMD ["node", "index.js"]
