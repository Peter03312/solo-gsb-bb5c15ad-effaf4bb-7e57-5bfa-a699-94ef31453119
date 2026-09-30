# syntax=docker/dockerfile:1

# ---------- stage 1: build React frontend ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: Python backend serving API + static ----------
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_PORT=8000 \
    POOL_DB_PATH=/app/data/pooling.db \
    POOL_STATIC_DIR=/app/static

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend /fe/dist ./static

RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
