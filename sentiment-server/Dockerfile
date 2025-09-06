FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev || npm i
COPY server.js .
EXPOSE 5004
CMD ["node", "server.js"]
