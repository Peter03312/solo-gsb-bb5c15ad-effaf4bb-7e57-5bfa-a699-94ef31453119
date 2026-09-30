"""业务服务层：计划创建、（重新）计算、锁定、复测、快照。"""
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .calc import q_conc, q_volume, take_volume, to_scaled_int
from .solver import SolverSample, solve_pools


class ServiceError(Exception):
    """可向用户展示的业务错误（API 层映射为 400/404）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- 个体可行性

def _individual_infeasible_reason(
    concentration: Decimal,
    available_volume: Decimal,
    target_dose: Decimal,
    min_pipette: Decimal,
    capacity: Decimal,
) -> tuple[Decimal, str | None]:
    """检查样本个体约束。返回 (取液量, 不可行原因或 None)。"""
    tv = take_volume(target_dose, concentration)
    if tv < min_pipette:
        return tv, (
            f"取液量 {tv} 低于移液量下限 {q_volume(min_pipette)}，无法移液"
        )
    if tv > available_volume:
        return tv, (
            f"取液量 {tv} 超过可用体积 {q_volume(available_volume)}"
        )
    if tv > capacity:
        return tv, (
            f"取液量 {tv} 超过单池体积上限 {q_volume(capacity)}，任何池都无法容纳"
        )
    return tv, None


# ---------------------------------------------------------------- 未安排诊断

def _diagnose_unassigned(
    sample: models.Sample,
    tv: Decimal,
    pool_contents: dict[int, list[models.Sample]],
    pool_totals: dict[int, Decimal],
    free_slots: list[int],
    capacity: Decimal,
) -> str:
    """对“可个体安排但最终未入池”的样本给出原因。"""
    reasons: list[str] = []

    if not free_slots:
        reasons.append("可用池数已用尽（所有池都已用于安排其他样本）")

    detail = []
    for pos in sorted(pool_contents.keys()):
        members = pool_contents[pos]
        total = pool_totals[pos]
        conflicts: list[str] = []
        idx = sample.index_sequence
        same = [m.code for m in members if m.index_sequence == idx]
        if same:
            conflicts.append(f"索引 {idx} 与样本 {'、'.join(same)} 重复")
        if total + tv > capacity:
            conflicts.append(f"加入后总体积 {q_volume(total + tv)} 超过上限 {q_volume(capacity)}")
        if conflicts:
            detail.append(f"池{pos}：{'；'.join(conflicts)}")
    if detail:
        reasons.append("现有各池均无法加入（" + "；".join(detail) + "）")
    if not reasons:
        reasons.append("在同时满足容量与索引约束的前提下无法排入（无可行分配）")
    return "。".join(reasons)


# ---------------------------------------------------------------- 快照

def _build_snapshot(
    exp: models.Experiment,
    pools: list[models.Pool],
    unarranged: list[dict],
    version_no: int,
    proven_optimal: bool,
) -> dict:
    pool_docs = []
    for p in pools:
        arranged = [a for a in p.assignments if a.status == "arranged"]
        pool_docs.append({
            "position": p.position,
            "locked": p.locked,
            "total_volume": str(
                sum((Decimal(a.take_volume) for a in arranged), Decimal(0))
            ),
            "members": [
                {
                    "sample_id": a.sample.id,
                    "code": a.sample.code,
                    "index_sequence": a.sample.index_sequence,
                    "concentration": a.sample.concentration,
                    "target_dose": a.sample.target_dose,
                    "take_volume": a.take_volume,
                }
                for a in arranged
            ],
        })
    return {
        "version_no": version_no,
        "proven_optimal": proven_optimal,
        "params": {
            "available_pools": exp.available_pools,
            "pool_capacity": exp.pool_capacity,
            "min_pipette_volume": exp.min_pipette_volume,
        },
        "pools": pool_docs,
        "unarranged": unarranged,
    }


def _add_version(
    db: Session,
    exp: models.Experiment,
    version_no: int,
    trigger: str,
    note: str | None,
    snapshot: dict,
    proven_optimal: bool,
) -> models.PlanVersion:
    version = models.PlanVersion(
        experiment_id=exp.id,
        version_no=version_no,
        trigger=trigger,
        note=note,
        proven_optimal=proven_optimal,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
    )
    db.add(version)
    return version


# ---------------------------------------------------------------- 核心重算

def recompute(
    db: Session,
    exp: models.Experiment,
    trigger: str,
    note: str | None = None,
) -> tuple[int, bool]:
    """（重新）计算所有未锁定池。锁定池保持原配方不动。

    在单个事务内完成：删除未锁池及其 assignment、求解、重建、生成版本快照。
    返回 (新版本号, 是否证明最优)。
    """
    capacity = q_volume(exp.pool_capacity)
    min_pipette = q_volume(exp.min_pipette_volume)

    # 1) 显式从数据库读取锁定池及其 assignment（不依赖可能陈旧的反向关系）
    locked_pools = [
        p for p in db.scalars(
            select(models.Pool).where(
                models.Pool.experiment_id == exp.id,
                models.Pool.locked.is_(True),
            ).order_by(models.Pool.position)
        ).all()
    ]
    locked_pool_ids = [p.id for p in locked_pools]
    locked_rows: list[models.PoolAssignment] = list(
        db.scalars(
            select(models.PoolAssignment)
            .where(models.PoolAssignment.pool_id.in_(locked_pool_ids))
        ).all()
    ) if locked_pool_ids else []
    locked_sample_ids = {a.sample_id for a in locked_rows}

    # 2) 先删除所有未锁定样本的 assignment（含 unarranged 记录），
    #    再删除未锁定池（避免 SQLite 外键级联差异）
    free_sample_ids = [
        s.id for s in exp.samples if s.id not in locked_sample_ids
    ]
    if free_sample_ids:
        db.execute(
            models.PoolAssignment.__table__.delete().where(
                models.PoolAssignment.sample_id.in_(free_sample_ids)
            )
        )
    db.execute(
        models.Pool.__table__.delete().where(
            models.Pool.experiment_id == exp.id,
            models.Pool.locked.is_(False),
        )
    )
    db.flush()
    # 让 exp 上的关系集合失效，后续重新从身份映射/库读取
    db.expire(exp, ["pools", "samples", "versions"])

    # 3) 未锁定样本逐个做可行性检查
    feasible: list[tuple[models.Sample, Decimal]] = []
    infeasible_reasons: dict[int, tuple[Decimal, str]] = {}
    for s in exp.samples:
        if s.id in locked_sample_ids:
            continue
        tv, reason = _individual_infeasible_reason(
            Decimal(s.concentration),
            Decimal(s.available_volume),
            Decimal(s.target_dose),
            min_pipette,
            capacity,
        )
        if reason:
            infeasible_reasons[s.id] = (tv, reason)
        else:
            feasible.append((s, tv))

    # 3) 锁定池已占用的槽位与体积
    used_positions = {p.position for p in locked_pools}
    free_slots = [
        pos for pos in range(1, exp.available_pools + 1) if pos not in used_positions
    ]
    locked_contents: dict[int, list[models.Sample]] = {}
    locked_totals: dict[int, Decimal] = {}
    for p in locked_pools:
        members = [a.sample for a in p.assignments if a.status == "arranged"]
        locked_contents[p.position] = members
        locked_totals[p.position] = sum(
            (Decimal(a.take_volume) for a in p.assignments), Decimal(0)
        )

    # 4) 求解
    solver_samples = [
        SolverSample(
            id=s.id,
            code=s.code,
            take_volume=to_scaled_int(tv),
            index_key=s.index_sequence,
        )
        for s, tv in feasible
    ]
    res = solve_pools(
        solver_samples,
        slots=free_slots,
        capacity=to_scaled_int(capacity),
    )
    if res.status == "unknown":
        # 求解器异常、连可行解都没有：宁可报错，绝不生成任何配方
        raise ServiceError(
            "求解器未能找到可行解，本次计算未生成任何配方；请稍后重试或减少样本数。",
            status_code=503,
        )

    # 5) 落库：新建池 + assignment
    tv_by_id = {s.id: tv for s, tv in feasible}
    sample_by_id = {s.id: s for s, _ in feasible}

    new_pools: dict[int, models.Pool] = {}
    version_no = max((v.version_no for v in exp.versions), default=0) + 1

    for slot in set(res.assignment.values()):
        pool = models.Pool(
            position=slot,
            version_no=version_no,
            locked=False,
            warnings_json=None,
        )
        pool.assignments = []
        exp.pools.append(pool)
        db.add(pool)
        new_pools[slot] = pool
    db.flush()

    for sid, slot in res.assignment.items():
        s = sample_by_id[sid]
        pool = new_pools[slot]
        a = models.PoolAssignment(
            sample=s,
            status="arranged",
            take_volume=str(tv_by_id[sid]),
            reason=None,
        )
        pool.assignments.append(a)
        db.add(a)

    # 6) 未安排样本（个体可行 + 个体不可行），写诊断
    new_contents: dict[int, list[models.Sample]] = {
        slot: [sample_by_id[sid] for sid, sl in res.assignment.items() if sl == slot]
        for slot in new_pools
    }
    new_totals: dict[int, Decimal] = {}
    for slot, members in new_contents.items():
        new_totals[slot] = sum((tv_by_id[m.id] for m in members), Decimal(0))

    all_contents = {**locked_contents, **new_contents}
    all_totals = {**locked_totals, **new_totals}

    unarranged_docs: list[dict] = []
    for sid in res.unassigned:
        s = sample_by_id[sid]
        tv = tv_by_id[sid]
        reason = _diagnose_unassigned(
            s, tv, all_contents, all_totals, free_slots, capacity
        )
        db.add(models.PoolAssignment(
            sample_id=sid, pool_id=None, status="unarranged",
            take_volume=str(tv), reason=reason,
        ))
        unarranged_docs.append({
            "sample_id": sid, "code": s.code, "reason": reason,
            "take_volume": str(tv),
        })
    for sid, (tv, reason) in infeasible_reasons.items():
        s = next(x for x in exp.samples if x.id == sid)
        db.add(models.PoolAssignment(
            sample_id=sid, pool_id=None, status="unarranged",
            take_volume=str(tv), reason=reason,
        ))
        unarranged_docs.append({
            "sample_id": sid, "code": s.code, "reason": reason,
            "take_volume": str(tv),
        })

    # 7) 版本快照
    db.flush()
    exp_pools = sorted(exp.pools, key=lambda p: p.position)
    snapshot = _build_snapshot(exp, exp_pools, unarranged_docs, version_no, res.optimal)
    _add_version(db, exp, version_no, trigger, note, snapshot, res.optimal)
    db.flush()
    return version_no, res.optimal


# ---------------------------------------------------------------- 锁定

def set_pool_locked(
    db: Session, exp: models.Experiment, position: int, locked: bool
) -> models.Pool:
    pool = next((p for p in exp.pools if p.position == position), None)
    if pool is None:
        raise ServiceError(f"池 {position} 不存在或尚未生成", 404)
    pool.locked = locked
    if not locked:
        # 解锁后清除历史警示；下次复测/加样重算时该池会重新参与计算
        pool.warnings_json = None
    db.flush()
    return pool


# ---------------------------------------------------------------- 复测

def apply_remeasure(
    db: Session,
    exp: models.Experiment,
    updates: list[dict],
) -> int:
    """更新复测浓度（可选更新可用体积），刷新锁定池警示并重算未锁定池。"""
    id_set = {u["sample_id"] for u in updates}
    found = {s.id: s for s in exp.samples}
    missing = id_set - set(found)
    if missing:
        raise ServiceError(f"样本不存在：{sorted(missing)}", 404)

    locked_pool_by_sample = {}
    for p in exp.pools:
        if p.locked:
            for a in p.assignments:
                locked_pool_by_sample[a.sample_id] = p

    changed: list[tuple[models.Sample, Decimal, Decimal | None, Decimal | None]] = []
    for u in updates:
        s = found[u["sample_id"]]
        old_conc = Decimal(s.concentration)
        new_conc = q_conc(u["concentration"])
        old_vol = Decimal(s.available_volume)
        new_vol = q_volume(u["available_volume"]) if u["available_volume"] is not None else None
        s.concentration = str(new_conc)
        if new_vol is not None:
            s.available_volume = str(new_vol)
        changed.append((s, old_conc, old_vol, new_vol))

    # 刷新锁定池警示：只针对本次复测涉及的锁定池样本
    capacity = q_volume(exp.pool_capacity)
    affected_pools: set[models.Pool] = set()
    for s, old_conc, old_vol, new_vol in changed:
        pool = locked_pool_by_sample.get(s.id)
        if pool is not None:
            affected_pools.add(pool)
    for pool in affected_pools:
        pool.warnings_json = json.dumps(
            _locked_pool_warnings(pool, capacity), ensure_ascii=False
        )

    version_no, _proven = recompute(
        db, exp, trigger="remeasure", note="复测浓度后重算未锁定池"
    )

    # 留痕（在版本号确定后写入）
    for s, old_conc, old_vol, new_vol in changed:
        db.add(models.ConcentrationLog(
            experiment_id=exp.id,
            sample_id=s.id,
            old_concentration=str(old_conc),
            new_concentration=s.concentration,
            old_available_volume=str(old_vol),
            new_available_volume=str(new_vol) if new_vol is not None else None,
            version_no=version_no,
        ))
    db.flush()
    return version_no


def _locked_pool_warnings(pool: models.Pool, capacity: Decimal) -> list[str]:
    """按当前样本数据复核锁定池配方，生成受影响警示。"""
    warnings: list[str] = []
    total = Decimal(0)
    for a in pool.assignments:
        s = a.sample
        old_tv = Decimal(a.take_volume)  # 原配方取液量，保持不变
        new_tv = take_volume(Decimal(s.target_dose), Decimal(s.concentration))
        if new_tv != old_tv:
            warnings.append(
                f"样本 {s.code}：浓度已复测，按新浓度取液量应为 {new_tv}，"
                f"锁定配方仍为 {old_tv}（未改动）"
            )
        if old_tv > Decimal(s.available_volume):
            warnings.append(
                f"样本 {s.code}：原配方取液量 {old_tv} 已超过当前可用体积 "
                f"{s.available_volume}，实际配制可能无法取样"
            )
        total += old_tv
    if total > capacity:
        warnings.append(
            f"池 {pool.position}：当前成员原配方取液量合计 {q_volume(total)}，"
            f"超过单池体积上限 {capacity}（配方锁定未改动，请人工复核）"
        )
    return warnings
