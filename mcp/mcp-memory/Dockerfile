FROM node:20-slim

ENV NODE_ENV=production \
    PORT=8470 \
    MEMORY_FILE_PATH=/data/memory.jsonl

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY index.js ./

EXPOSE 8470

CMD ["node", "index.js"]
