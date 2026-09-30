"""FastAPI application: sequencing sample pooling workbench."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import schemas, service
from .db import init_db
from .optimizer import OptimizerError

app = FastAPI(title="测序样本拼池工作台", version="1.0.0")


@app.exception_handler(service.ServiceError)
async def service_error_handler(request: Request, exc: service.ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail})


@app.exception_handler(OptimizerError)
async def optimizer_error_handler(request: Request, exc: OptimizerError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/batches")
def api_list_batches() -> list[dict]:
    return service.list_batches()


@app.post("/api/batches", status_code=201)
def api_create_batch(payload: schemas.BatchCreate) -> dict:
    return service.create_batch(
        payload.name, payload.num_pools, payload.max_pool_volume, payload.min_transfer
    )


@app.get("/api/batches/{batch_id}")
def api_get_batch(batch_id: int) -> dict:
    return service.get_batch(batch_id)


@app.delete("/api/batches/{batch_id}", status_code=204)
def api_delete_batch(batch_id: int):
    service.delete_batch(batch_id)


@app.get("/api/batches/{batch_id}/samples")
def api_list_samples(batch_id: int) -> list[dict]:
    return service.list_samples(batch_id)


@app.post("/api/batches/{batch_id}/samples", status_code=201)
def api_add_samples(batch_id: int, payload: schemas.SampleBulkIn) -> dict:
    data = [s.model_dump() for s in payload.samples]
    return service.add_samples(batch_id, data)


@app.delete("/api/batches/{batch_id}/samples/{sample_id}", status_code=200)
def api_delete_sample(batch_id: int, sample_id: int) -> dict:
    return service.delete_sample(batch_id, sample_id)


@app.post("/api/batches/{batch_id}/plan", status_code=200)
def api_plan(batch_id: int) -> dict:
    return service.plan_batch(batch_id, trigger="manual")


@app.post("/api/batches/{batch_id}/pools/{pool_no}/lock")
def api_lock(batch_id: int, pool_no: int) -> dict:
    return service.set_lock(batch_id, pool_no, True)


@app.post("/api/batches/{batch_id}/pools/{pool_no}/unlock")
def api_unlock(batch_id: int, pool_no: int) -> dict:
    return service.set_lock(batch_id, pool_no, False)


@app.post("/api/batches/{batch_id}/samples/{sample_id}/remeasure")
def api_remeasure(batch_id: int, sample_id: int, payload: schemas.RemeasureIn) -> dict:
    return service.remeasure(batch_id, sample_id, payload.concentration)


# Serve the built React SPA from /app/static. Real files are served directly;
# any other non-API GET path falls back to index.html (client-side routing).
STATIC_DIR = os.environ.get("POOL_STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static"))
if Path(STATIC_DIR).is_dir():
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = Path(STATIC_DIR) / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(Path(STATIC_DIR) / "index.html")

    if (Path(STATIC_DIR) / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=Path(STATIC_DIR) / "assets"), name="assets")
