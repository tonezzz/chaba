FROM mcr.microsoft.com/playwright:v1.48.2-jammy

ENV NODE_ENV=production \
    PORT=8025

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY . .

RUN mkdir -p /app/output /app/scenarios

EXPOSE 8025

CMD ["node", "index.js"]
