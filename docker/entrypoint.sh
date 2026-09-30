#!/bin/sh
# 容器入口：初始化数据库（建表，幂等）后启动服务
set -e

echo "[entrypoint] 初始化数据库: ${SQLALCHEMY_URL:-sqlite:///$DB_PATH}"
python -m app.init_db

echo "[entrypoint] 启动 FastAPI 服务 …"
exec "$@"
