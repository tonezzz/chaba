FROM node:20-slim

ENV NODE_ENV=production \
    PORT=8046

WORKDIR /app

COPY package*.json ./
RUN npm install --production

COPY . .

EXPOSE 8046

CMD ["node", "index.js"]
