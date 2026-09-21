# Фронт для разработки: vite dev server, код приезжает bind-mount'ом.
FROM node:24-alpine

WORKDIR /app

# Отдельный слой: правки кода не пересобирают node_modules.
COPY package.json package-lock.json ./
RUN npm ci

EXPOSE 5420
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
