# ---- 前端构建阶段 ----
FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 后端运行阶段 ----
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/data/pooling.db \
    STATIC_DIR=/app/frontend/dist

# 后端代码（WORKDIR 位于此，python -m app.* 可直接解析）
WORKDIR /app/backend

# 后端依赖
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 后端代码
COPY backend/ /app/backend/

# 前端构建产物（由 FastAPI 在同端口托管）
COPY --from=frontend-builder /build/frontend/dist /app/frontend/dist

# 持久化数据目录
RUN mkdir -p /data
VOLUME ["/data"]

COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
