FROM node:20-alpine

ENV NODE_ENV=production \
    PORT=8182

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY . .

EXPOSE 8182

CMD ["node", "index.js"]
