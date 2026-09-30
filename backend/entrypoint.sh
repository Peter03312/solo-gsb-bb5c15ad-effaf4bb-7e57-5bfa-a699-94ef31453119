#!/bin/sh
set -e

echo "初始化数据库 ..."
python init_db.py

echo "启动 Web 服务，监听 0.0.0.0:${WEB_PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${WEB_PORT:-8000}"
