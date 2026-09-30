"""FastAPI 路由与序列化。"""
import json
from datetime import timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import models, schemas, services
from .calc import q_conc, q_volume
from .database import get_db
from .services import ServiceError

router = APIRouter(prefix="/api")


def _iso(dt) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _get_experiment(db: Session, exp_id: int) -> models.Experiment:
    exp = db.get(models.Experiment, exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    return exp


def _assignment_out(a: models.PoolAssignment) -> schemas.AssignmentOut:
    s = a.sample
    return schemas.AssignmentOut(
        sample_id=s.id,
        code=s.code,
        index_sequence=s.index_sequence,
        concentration=Decimal(s.concentration),
        target_dose=Decimal(s.target_dose),
        available_volume=Decimal(s.available_volume),
        take_volume=Decimal(a.take_volume) if a.take_volume is not None else None,
        status=a.status,  # type: ignore[arg-type]
        reason=a.reason,
    )


def _serialize_detail(exp: models.Experiment) -> schemas.ExperimentDetail:
    pools_out: list[schemas.PoolOut] = []
    arranged_ids: set[int] = set()
    for p in sorted(exp.pools, key=lambda x: x.position):
        members = [a for a in p.assignments if a.status == "arranged"]
        total = sum((Decimal(a.take_volume) for a in members), Decimal(0))
        arranged_ids.update(a.sample_id for a in members)
        pools_out.append(schemas.PoolOut(
            pool_id=p.id,
            position=p.position,
            locked=p.locked,
            version_no=p.version_no,
            total_volume=q_volume(total),
            warnings=json.loads(p.warnings_json) if p.warnings_json else [],
            assignments=[_assignment_out(a) for a in sorted(members, key=lambda x: x.id)],
        ))

    # 未安排样本：每个样本当前只有一条 assignment 记录
    unarranged_rows: list[models.PoolAssignment] = []
    for s in sorted(exp.samples, key=lambda x: x.id):
        cur = next((a for a in s.assignments), None)
        if cur is not None and cur.status == "unarranged":
            unarranged_rows.append(cur)

    versions = [
        schemas.VersionBrief(
            version_no=v.version_no,
            trigger=v.trigger,
            note=v.note,
            created_at=_iso(v.created_at),
            pool_count=len(json.loads(v.snapshot_json)["pools"]),
            arranged_count=sum(
                len(p["members"]) for p in json.loads(v.snapshot_json)["pools"]
            ),
            proven_optimal=v.proven_optimal,
        )
        for v in sorted(exp.versions, key=lambda x: x.version_no)
    ]
    current_version = max((v.version_no for v in exp.versions), default=0)

    return schemas.ExperimentDetail(
        id=exp.id,
        name=exp.name,
        available_pools=exp.available_pools,
        pool_capacity=Decimal(exp.pool_capacity),
        min_pipette_volume=Decimal(exp.min_pipette_volume),
        created_at=_iso(exp.created_at),
        samples=[schemas.SampleOut.model_validate(s) for s in exp.samples],
        pools=pools_out,
        unarranged=[_assignment_out(a) for a in unarranged_rows],
        versions=versions,
        current_version=current_version,
    )


# ---------------------------------------------------------------- 列表/创建

@router.get("/experiments", response_model=list[schemas.ExperimentSummary])
def list_experiments(db: Session = Depends(get_db)):
    exps = db.scalars(
        select(models.Experiment)
        .options(
            selectinload(models.Experiment.samples).selectinload(models.Sample.assignments),
            selectinload(models.Experiment.versions),
            selectinload(models.Experiment.pools).selectinload(models.Pool.assignments),
        )
        .order_by(models.Experiment.id.desc())
    ).all()
    result = []
    for exp in exps:
        arranged = sum(
            1
            for p in exp.pools
            for a in p.assignments if a.status == "arranged"
        )
        result.append(schemas.ExperimentSummary(
            id=exp.id,
            name=exp.name,
            available_pools=exp.available_pools,
            created_at=_iso(exp.created_at),
            current_version=max((v.version_no for v in exp.versions), default=0),
            pool_count=len(exp.pools),
            arranged_count=arranged,
            total_samples=len(exp.samples),
        ))
    return result


@router.post("/experiments", response_model=schemas.ExperimentDetail, status_code=201)
def create_experiment(payload: schemas.ExperimentCreate, db: Session = Depends(get_db)):
    if payload.min_pipette_volume > payload.pool_capacity:
        raise HTTPException(
            status_code=422,
            detail="移液量下限不能大于单池体积上限",
        )
    exp = models.Experiment(
        name=payload.name,
        available_pools=payload.available_pools,
        pool_capacity=str(q_volume(payload.pool_capacity)),
        min_pipette_volume=str(q_volume(payload.min_pipette_volume)),
    )
    db.add(exp)
    db.flush()
    for s in payload.samples:
        db.add(models.Sample(
            experiment_id=exp.id,
            code=s.code,
            concentration=str(q_conc(s.concentration)),
            available_volume=str(q_volume(s.available_volume)),
            target_dose=str(q_volume(s.target_dose)),
            index_sequence=s.index_sequence,
        ))
    db.flush()
    try:
        services.recompute(db, exp, trigger="create", note="首次计算")
        db.commit()
    except ServiceError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message)
    db.refresh(exp)
    return _serialize_detail(exp)


@router.get("/experiments/{exp_id}", response_model=schemas.ExperimentDetail)
def get_experiment(exp_id: int, db: Session = Depends(get_db)):
    return _serialize_detail(_get_experiment(db, exp_id))


@router.delete("/experiments/{exp_id}", status_code=204)
def delete_experiment(exp_id: int, db: Session = Depends(get_db)):
    exp = _get_experiment(db, exp_id)
    db.delete(exp)
    db.commit()


# ---------------------------------------------------------------- 追加样本

@router.post("/experiments/{exp_id}/samples",
             response_model=schemas.ExperimentDetail, status_code=201)
def add_samples(exp_id: int, payload: schemas.SamplesAdd, db: Session = Depends(get_db)):
    exp = _get_experiment(db, exp_id)
    existing = {s.code for s in exp.samples}
    dup = existing & {s.code for s in payload.samples}
    if dup:
        raise HTTPException(status_code=422, detail=f"样本编号已存在：{', '.join(sorted(dup))}")
    for s in payload.samples:
        db.add(models.Sample(
            experiment_id=exp.id,
            code=s.code,
            concentration=str(q_conc(s.concentration)),
            available_volume=str(q_volume(s.available_volume)),
            target_dose=str(q_volume(s.target_dose)),
            index_sequence=s.index_sequence,
        ))
    db.flush()
    try:
        services.recompute(db, exp, trigger="add_samples", note="追加样本后重算未锁定池")
        db.commit()
    except ServiceError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message)
    db.refresh(exp)
    return _serialize_detail(exp)


# ---------------------------------------------------------------- 锁定/解锁

@router.post("/experiments/{exp_id}/pools/{position}/lock",
             response_model=schemas.ExperimentDetail)
def lock_pool(exp_id: int, position: int, locked: bool = True,
              db: Session = Depends(get_db)):
    exp = _get_experiment(db, exp_id)
    try:
        services.set_pool_locked(db, exp, position, locked)
        db.commit()
    except ServiceError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return _serialize_detail(exp)


# ---------------------------------------------------------------- 复测

@router.post("/experiments/{exp_id}/remeasure",
             response_model=schemas.ExperimentDetail)
def remeasure(exp_id: int, payload: schemas.RemeasureRequest,
              db: Session = Depends(get_db)):
    exp = _get_experiment(db, exp_id)
    try:
        services.apply_remeasure(
            db, exp,
            [u.model_dump() for u in payload.updates],
        )
        db.commit()
    except ServiceError as e:
        db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.message)
    db.refresh(exp)
    return _serialize_detail(exp)


# ---------------------------------------------------------------- 版本历史

@router.get("/experiments/{exp_id}/versions/{version_no}")
def get_version(exp_id: int, version_no: int, db: Session = Depends(get_db)):
    exp = _get_experiment(db, exp_id)
    v = next((x for x in exp.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "version_no": v.version_no,
        "trigger": v.trigger,
        "note": v.note,
        "proven_optimal": v.proven_optimal,
        "created_at": _iso(v.created_at),
        "snapshot": json.loads(v.snapshot_json),
    }
