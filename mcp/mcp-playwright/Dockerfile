FROM mcr.microsoft.com/playwright:v1.57.0-jammy

ENV NODE_ENV=production \
    PORT=8260

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p /app/output /app/scenarios

EXPOSE $PORT

CMD ["node", "index.js"]
