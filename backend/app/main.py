"""FastAPI 入口：API + 前端静态资源托管 + 启动时初始化数据库。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine
from .routers import router

# 导入模型以确保表元数据已注册
from . import models  # noqa: F401

STATIC_DIR = os.environ.get("STATIC_DIR", "/app/frontend/dist")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 一键启动：自动建库建表（幂等）
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="测序样本拼池工作台", version="1.0.0", lifespan=lifespan)

app.include_router(router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 前端静态资源（生产由本服务同端口托管）；开发环境下该目录可不存在
if os.path.isdir(STATIC_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=os.path.join(STATIC_DIR, "assets")),
        name="assets",
    )

    @app.api_route(
        "/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False
    )
    def spa(full_path: str):
        # /api 下未命中的路径返回 404 JSON；其余路径统一回退到 SPA 入口
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
