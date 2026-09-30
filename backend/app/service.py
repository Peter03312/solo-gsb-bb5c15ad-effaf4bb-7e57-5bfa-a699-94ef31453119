"""Business logic: batches, samples, planning, locking and re-measurement."""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from . import optimizer
from .db import connect, now_iso


class ServiceError(Exception):
    """Expected, user-facing error (maps to HTTP 4xx)."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


# ---------------------------------------------------------------- helpers

def _row_to_sample(r: sqlite3.Row) -> dict:
    need = r["target_amount"] / r["concentration"]
    return {
        "id": r["id"],
        "batch_id": r["batch_id"],
        "name": r["name"],
        "concentration": r["concentration"],
        "available_volume": r["available_volume"],
        "target_amount": r["target_amount"],
        "index_seq": r["index_seq"],
        "transfer_need": round(need, 6),
        "created_at": r["created_at"],
    }


def _get_batch(conn: sqlite3.Connection, batch_id: int) -> sqlite3.Row:
    b = conn.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
    if not b:
        raise ServiceError(404, "批次不存在")
    return b


def _latest_plan(conn: sqlite3.Connection, batch_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM plans WHERE batch_id=? ORDER BY version DESC LIMIT 1",
        (batch_id,),
    ).fetchone()


def _locked_pools(conn: sqlite3.Connection, batch_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM pools WHERE batch_id=? AND locked=1 ORDER BY pool_no",
        (batch_id,),
    ).fetchall()


def _sample_map(conn: sqlite3.Connection, batch_id: int) -> dict[int, sqlite3.Row]:
    return {
        r["id"]: r
        for r in conn.execute("SELECT * FROM samples WHERE batch_id=?", (batch_id,)).fetchall()
    }


# ---------------------------------------------------------------- batches / samples

def create_batch(name: str, num_pools: int, max_pool_volume: float, min_transfer: float) -> dict:
    conn = connect()
    try:
        exists = conn.execute("SELECT 1 FROM batches WHERE name=?", (name,)).fetchone()
        if exists:
            raise ServiceError(409, f"批次名称已存在: {name}")
        cur = conn.execute(
            "INSERT INTO batches (name, num_pools, max_pool_volume, min_transfer, created_at) VALUES (?,?,?,?,?)",
            (name, int(num_pools), float(max_pool_volume), float(min_transfer), now_iso()),
        )
        conn.commit()
        return get_batch(cur.lastrowid)
    finally:
        conn.close()


def list_batches() -> list[dict]:
    conn = connect()
    try:
        out = []
        for b in conn.execute("SELECT * FROM batches ORDER BY id DESC").fetchall():
            plan = _latest_plan(conn, b["id"])
            out.append(
                {
                    "id": b["id"],
                    "name": b["name"],
                    "num_pools": b["num_pools"],
                    "max_pool_volume": b["max_pool_volume"],
                    "min_transfer": b["min_transfer"],
                    "created_at": b["created_at"],
                    "sample_count": conn.execute(
                        "SELECT COUNT(*) c FROM samples WHERE batch_id=?", (b["id"],)
                    ).fetchone()["c"],
                    "has_plan": plan is not None,
                    "version": plan["version"] if plan else 0,
                    "locked_count": conn.execute(
                        "SELECT COUNT(*) c FROM pools WHERE batch_id=? AND locked=1", (b["id"],)
                    ).fetchone()["c"],
                }
            )
        return out
    finally:
        conn.close()


def delete_batch(batch_id: int) -> None:
    conn = connect()
    try:
        _get_batch(conn, batch_id)
        conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
        conn.commit()
    finally:
        conn.close()


def list_samples(batch_id: int) -> list[dict]:
    conn = connect()
    try:
        _get_batch(conn, batch_id)
        return [
            _row_to_sample(r)
            for r in conn.execute(
                "SELECT * FROM samples WHERE batch_id=? ORDER BY id", (batch_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


def add_samples(batch_id: int, samples: list[dict]) -> dict:
    """samples: list of validated dicts. Replans unlocked pools when a plan exists."""
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        existing = {
            r["name"]
            for r in conn.execute("SELECT name FROM samples WHERE batch_id=?", (batch_id,)).fetchall()
        }
        incoming: set[str] = set()
        for s in samples:
            if s["name"] in existing or s["name"] in incoming:
                raise ServiceError(409, f"样本名称重复: {s['name']}")
            incoming.add(s["name"])
        ts = now_iso()
        for s in samples:
            conn.execute(
                """INSERT INTO samples
                   (batch_id, name, concentration, available_volume, target_amount, index_seq, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    batch_id,
                    s["name"],
                    float(s["concentration"]),
                    float(s["available_volume"]),
                    float(s["target_amount"]),
                    s["index_seq"],
                    ts,
                ),
            )
        conn.commit()

        plan = _latest_plan(conn, batch_id)
        warnings: list[str] = []
        if plan is not None:
            _plan(conn, b, trigger="add_samples", warnings=warnings)
        result = get_batch(batch_id)
        result["replanned"] = plan is not None
        return result
    finally:
        conn.close()


def delete_sample(batch_id: int, sample_id: int) -> dict:
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        locked = conn.execute(
            """SELECT 1 FROM assignments a JOIN pools p ON p.id=a.pool_id
               WHERE a.sample_id=? AND p.locked=1""",
            (sample_id,),
        ).fetchone()
        if locked:
            raise ServiceError(409, "该样本属于已锁定池，请先解锁该池后再删除")
        cur = conn.execute(
            "DELETE FROM samples WHERE id=? AND batch_id=?", (sample_id, batch_id)
        )
        if cur.rowcount == 0:
            raise ServiceError(404, "样本不存在")
        conn.commit()
        if _latest_plan(conn, batch_id) is not None:
            _plan(conn, b, trigger="delete_sample")
        return get_batch(batch_id)
    finally:
        conn.close()


# ---------------------------------------------------------------- planning

def _diagnose(
    sample: sqlite3.Row,
    need: float,
    cfg: sqlite3.Row,
    used_bins: set[int],
    locked_bins: set[int],
    free_bins: list[int],
    K: int,
    blocked_by_index: dict[int, set[int]],
    feasible_by_bins: dict[int, set[int]],
) -> list[str]:
    """Explain why an individually-feasible sample could not be placed.

    The MILP may only use non-locked bins. ``feasible_by_bins`` = bins with
    enough residual volume; ``blocked_by_index`` = bins carrying the same index.
    """
    roomy = feasible_by_bins.get(sample["id"], set())
    idx_blocked = blocked_by_index.get(sample["id"], set())
    roomy_idx = roomy & idx_blocked                      # fits, same index
    tight_idx = idx_blocked - roomy                      # same index, no room
    roomy_locked = (roomy - idx_blocked) & locked_bins   # would fit, but pool locked
    no_room = used_bins - roomy - idx_blocked
    no_room_locked = no_room & locked_bins
    no_room_unlocked = no_room - locked_bins
    reasons: list[str] = []

    if roomy_idx:
        reasons.append(
            f"{len(roomy_idx)} 个池剩余空间足够但含相同索引 {sample['index_seq']}，同池索引不得重复"
        )
    if roomy_locked:
        reasons.append(
            f"{len(roomy_locked)} 个池剩余空间足够但已锁定，锁定池保留原配方不可加入"
        )
    if tight_idx:
        reasons.append(
            f"{len(tight_idx)} 个池含相同索引 {sample['index_seq']} 且剩余空间不足"
        )
    if no_room_unlocked:
        reasons.append(
            f"{len(no_room_unlocked)} 个未锁定池剩余空间不足（取液量 {round(need, 3)} µL 超过池剩余体积）"
        )
    if no_room_locked:
        reasons.append(
            f"{len(no_room_locked)} 个已锁定池剩余空间不足，且锁定池不可修改"
        )
    if not used_bins and not free_bins:
        reasons.append("没有任何可用池（可用池数为 0）")
    if not reasons:
        reasons.append(f"全部 {K} 个池均无法接纳该样本（索引冲突、空间不足或已锁定）")
    return reasons


def _plan(
    conn: sqlite3.Connection,
    batch: sqlite3.Row,
    trigger: str,
    warnings: Optional[list[str]] = None,
    changed_sample_ids: Optional[set[int]] = None,
    old_placement: Optional[dict[int, int]] = None,
) -> dict:
    """(Re)compute the plan for all unlocked pools. Locked pools are preserved as-is."""
    if warnings is None:
        warnings = []
    changed_sample_ids = changed_sample_ids or set()
    batch_id = batch["id"]
    K = batch["num_pools"]
    cap = batch["max_pool_volume"]
    min_t = batch["min_transfer"]

    all_samples = _sample_map(conn, batch_id)
    locked_rows = _locked_pools(conn, batch_id)
    locked_bins = {r["pool_no"] - 1 for r in locked_rows}

    # Preserve old layout snapshot (before deleting unlocked pools) for warnings.
    if old_placement is None:
        old_placement = {}
        old_plan = _latest_plan(conn, batch_id)
        if old_plan is not None:
            for a in conn.execute(
                "SELECT a.sample_id, a.pool_no FROM assignments a JOIN pools p ON p.id=a.pool_id WHERE p.plan_id=?",
                (old_plan["id"],),
            ).fetchall():
                old_placement[a["sample_id"]] = a["pool_no"]

    # Locked pools occupy bins and carry residual capacity / occupied indexes.
    locked_volume = [0.0] * K
    locked_index: list[set[str]] = [set() for _ in range(K)]
    locked_ids: set[int] = set()
    for r in locked_rows:
        b = r["pool_no"] - 1
        for a in conn.execute("SELECT * FROM assignments WHERE pool_id=?", (r["id"],)).fetchall():
            locked_volume[b] += a["transfer_volume"]
            locked_index[b].add(a["index_seq"])
            locked_ids.add(a["sample_id"])

    # Filter samples for the unlocked optimisation.
    candidates: list[optimizer.Sample] = []
    infeasible: list[tuple[sqlite3.Row, float, list[str]]] = []
    for sid, s in all_samples.items():
        if sid in locked_ids:
            continue
        need = s["target_amount"] / s["concentration"]
        reasons: list[str] = []
        if need < min_t - 1e-9:
            reasons.append(f"取液量 {round(need, 3)} 低于移液量下限 {min_t}")
        if need > s["available_volume"] + 1e-9:
            reasons.append(f"取液量 {round(need, 3)} 超过可用体积 {s['available_volume']}")
        if need > cap + 1e-9:
            reasons.append(f"取液量 {round(need, 3)} 超过单池体积上限 {cap}")
        if reasons:
            infeasible.append((s, need, reasons))
        else:
            candidates.append(
                optimizer.Sample(sid, s["name"], s["index_seq"], s["concentration"], need)
            )

    # Locked pools are immutable ("保留原配方"): free samples may only be
    # arranged into the remaining, completely unused pool positions.
    free_bins = sorted(b for b in range(K) if b not in locked_bins)
    if free_bins:
        opt_result = optimizer.solve(candidates, len(free_bins), cap)
        # map compact pool positions back to original pool numbers (1-based)
        for pr in opt_result.pools:
            pr.pool_no = free_bins[pr.pool_no - 1] + 1
    else:
        opt_result = optimizer.OptimizeResult(pools=[], placed_ids=set(), candidate_ids=[])

    placed = opt_result.placed_ids
    unplaced_rows: list[tuple[sqlite3.Row, float, list[str]]] = list(infeasible)

    # Final layout diagnostics for feasible-but-unplaced samples.
    used_bins: set[int] = {pr.pool_no - 1 for pr in opt_result.pools}
    used_bins |= locked_bins
    placed_volume = list(locked_volume)
    placed_index: list[set[str]] = [set(x) for x in locked_index]
    for pr in opt_result.pools:
        b = pr.pool_no - 1
        for it in pr.samples:
            placed_volume[b] += it["transfer_volume"]
            placed_index[b].add(it["index_seq"])

    blocked_by_index: dict[int, set[int]] = {}
    feasible_by_bins: dict[int, set[int]] = {}
    for cand in candidates:
        if cand.sid in placed:
            continue
        feas: set[int] = set()
        idx_block: set[int] = set()
        for b in used_bins:
            if cand.index_seq in placed_index[b]:
                idx_block.add(b)
            if placed_volume[b] + cand.transfer_need <= cap + 1e-9:
                feas.add(b)
        feasible_by_bins[cand.sid] = feas
        blocked_by_index[cand.sid] = idx_block

    for cand in candidates:
        if cand.sid in placed:
            continue
        reasons = _diagnose(
            all_samples[cand.sid],
            cand.transfer_need,
            batch,
            used_bins,
            locked_bins,
            free_bins,
            K,
            blocked_by_index,
            feasible_by_bins,
        )
        unplaced_rows.append((all_samples[cand.sid], cand.transfer_need, reasons))

    # Aggregate structural warnings.
    index_groups: dict[str, int] = {}
    for cand in candidates:
        index_groups[cand.index_seq] = index_groups.get(cand.index_seq, 0) + 1
    for idx, cnt in index_groups.items():
        if cnt > K:
            warnings.append(f"索引 {idx} 有 {cnt} 个样本，但仅有 {K} 个池，至少 {cnt - K} 个无法安排")

    # ---- persist ----
    old_plan = _latest_plan(conn, batch_id)
    version = (old_plan["version"] + 1) if old_plan else 1

    # snapshot old unlocked placements for diff warnings
    if changed_sample_ids:
        for sid in changed_sample_ids:
            old_no = old_placement.get(sid)
            new_no = None
            for pr in opt_result.pools:
                if any(it["sample_id"] == sid for it in pr.samples):
                    new_no = pr.pool_no
            nm = all_samples[sid]["name"] if sid in all_samples else f"#{sid}"
            if old_no is not None and new_no is not None and old_no != new_no:
                warnings.append(f"复测样本 {nm} 由池 {old_no} 调整至池 {new_no}")
            elif old_no is not None and new_no is None:
                warnings.append(f"复测样本 {nm} 已变为无法安排（原池 {old_no}）")

    cur = conn.execute(
        "INSERT INTO plans (batch_id, version, created_at, trigger, summary) VALUES (?,?,?,?,?)",
        (batch_id, version, now_iso(), trigger, "{}"),
    )
    plan_id = cur.lastrowid

    # Replace unlocked pools; locked pools survive unchanged but are attached
    # to the new plan version so the latest plan shows the full layout.
    conn.execute(
        "DELETE FROM pools WHERE batch_id=? AND locked=0", (batch_id,)
    )
    conn.execute(
        "UPDATE pools SET plan_id=? WHERE batch_id=? AND locked=1",
        (plan_id, batch_id),
    )

    new_numbers = {pr.pool_no - 1 for pr in opt_result.pools}
    assert not (new_numbers & locked_bins), "新方案不得占用锁定池编号"

    new_placement: dict[int, int] = {}
    for pr in opt_result.pools:
        pc = conn.execute(
            "INSERT INTO pools (batch_id, plan_id, pool_no, locked) VALUES (?,?,?,0)",
            (batch_id, plan_id, pr.pool_no),
        )
        pool_id = pc.lastrowid
        for it in pr.samples:
            s = all_samples[it["sample_id"]]
            conn.execute(
                """INSERT INTO assignments
                   (pool_id, sample_id, pool_no, transfer_volume, concentration, target_amount, index_seq)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    pool_id,
                    it["sample_id"],
                    pr.pool_no,
                    it["transfer_volume"],
                    s["concentration"],
                    s["target_amount"],
                    s["index_seq"],
                ),
            )
            new_placement[it["sample_id"]] = pr.pool_no

    for s, need, reasons in unplaced_rows:
        conn.execute(
            "INSERT INTO unassigned (plan_id, sample_id, name, index_seq, concentration, transfer_need, reasons) VALUES (?,?,?,?,?,?,?)",
            (
                plan_id,
                s["id"],
                s["name"],
                s["index_seq"],
                s["concentration"],
                round(need, 6),
                json.dumps(reasons, ensure_ascii=False),
            ),
        )

    # warnings for samples displaced by replan (not caused by remeasure of themselves)
    if trigger in ("unlock", "add_samples", "delete_sample"):
        for sid, old_no in old_placement.items():
            if sid in locked_ids or sid not in all_samples:
                continue
            new_no = new_placement.get(sid)
            if new_no is not None and new_no != old_no:
                warnings.append(f"样本 {all_samples[sid]['name']} 由池 {old_no} 调整至池 {new_no}")

    total_assigned = len(locked_ids) + len(placed)
    total_samples = len(all_samples)
    summary = {
        "total_samples": total_samples,
        "assigned": total_assigned,
        "unassigned": total_samples - total_assigned,
        "pools_used": len(used_bins),
        "pools_available": K,
        "pools_locked": len(locked_rows),
        "warnings": warnings,
    }
    conn.execute("UPDATE plans SET summary=? WHERE id=?", (json.dumps(summary, ensure_ascii=False), plan_id))
    conn.execute(
        "INSERT INTO plan_versions (plan_id, batch_id, version, created_at, trigger, note, warnings_json) VALUES (?,?,?,?,?,?,?)",
        (
            plan_id,
            batch_id,
            version,
            now_iso(),
            trigger,
            f"安排 {total_assigned}/{total_samples} 个样本，使用 {len(used_bins)}/{K} 个池",
            json.dumps(warnings, ensure_ascii=False),
        ),
    )
    conn.commit()
    return get_batch(batch_id)


def plan_batch(batch_id: int, trigger: str = "manual") -> dict:
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        if not conn.execute("SELECT 1 FROM samples WHERE batch_id=?", (batch_id,)).fetchall():
            raise ServiceError(400, "请先录入样本后再生成方案")
        return _plan(conn, b, trigger=trigger)
    finally:
        conn.close()


# ---------------------------------------------------------------- lock / unlock

def set_lock(batch_id: int, pool_no: int, locked: bool) -> dict:
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        plan = _latest_plan(conn, batch_id)
        if not plan:
            raise ServiceError(400, "尚未生成方案")
        pool = conn.execute(
            "SELECT * FROM pools WHERE batch_id=? AND pool_no=?", (batch_id, pool_no)
        ).fetchone()
        if not pool:
            raise ServiceError(404, f"池 {pool_no} 不存在（当前方案未使用该池位）")
        if locked:
            if pool["locked"]:
                raise ServiceError(409, "该池已锁定")
            items = conn.execute(
                """SELECT a.*, s.name FROM assignments a JOIN samples s ON s.id=a.sample_id
                   WHERE a.pool_id=? ORDER BY a.id""",
                (pool["id"],),
            ).fetchall()
            recipe = {
                "pool_no": pool_no,
                "locked_at": now_iso(),
                "config": {
                    "max_pool_volume": b["max_pool_volume"],
                    "min_transfer": b["min_transfer"],
                },
                "items": [
                    {
                        "sample_id": a["sample_id"],
                        "name": a["name"],
                        "index_seq": a["index_seq"],
                        "concentration_at_lock": a["concentration"],
                        "target_amount": a["target_amount"],
                        "transfer_volume": a["transfer_volume"],
                    }
                    for a in items
                ],
                "total_volume": round(sum(a["transfer_volume"] for a in items), 6),
            }
            conn.execute(
                "UPDATE pools SET locked=1, locked_at=?, recipe_json=? WHERE id=?",
                (now_iso(), json.dumps(recipe, ensure_ascii=False), pool["id"]),
            )
            conn.commit()
        else:
            if not pool["locked"]:
                raise ServiceError(409, "该池未锁定")
            conn.execute(
                "UPDATE pools SET locked=0, locked_at=NULL, recipe_json=NULL WHERE id=?",
                (pool["id"],),
            )
            conn.commit()
            _plan(conn, b, trigger="unlock")
        return get_batch(batch_id)
    finally:
        conn.close()


# ---------------------------------------------------------------- re-measurement

def remeasure(batch_id: int, sample_id: int, new_concentration: float) -> dict:
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        s = conn.execute(
            "SELECT * FROM samples WHERE id=? AND batch_id=?", (sample_id, batch_id)
        ).fetchone()
        if not s:
            raise ServiceError(404, "样本不存在")
        old_conc = s["concentration"]
        if abs(new_concentration - old_conc) < 1e-12:
            raise ServiceError(422, "复测浓度与原值相同，无需重算")

        warnings: list[str] = []
        locked_row = conn.execute(
            """SELECT p.* FROM pools p JOIN assignments a ON a.pool_id=p.id
               WHERE a.sample_id=? AND p.locked=1""",
            (sample_id,),
        ).fetchone()

        conn.execute(
            "UPDATE samples SET concentration=? WHERE id=?", (float(new_concentration), sample_id)
        )

        if locked_row is not None:
            # locked pool: keep recipe, surface warning + version trail, no replan
            recipe = json.loads(locked_row["recipe_json"])
            new_need = s["target_amount"] / new_concentration
            old_need = s["target_amount"] / old_conc
            cap = b["max_pool_volume"]
            min_t = b["min_transfer"]
            pool_warn = (
                f"样本 {s['name']} 复测浓度 {old_conc} → {new_concentration}，"
                f"所在池 {locked_row['pool_no']} 已锁定，保留原配方；"
                f"若按新浓度重算取液量为 {round(new_need, 3)}（原 {round(old_need, 3)}）"
            )
            violations = []
            if new_need < min_t - 1e-9:
                violations.append(f"低于移液量下限 {min_t}")
            if new_need > s["available_volume"] + 1e-9:
                violations.append(f"超过可用体积 {s['available_volume']}")
            if violations:
                pool_warn += "；新取液量" + "、".join(violations)
            warnings.append(pool_warn)

            # Version trail without changing pools. The latest plan remains the
            # displayed plan, so carry its summary and unassigned rows forward.
            prev = _latest_plan(conn, batch_id)
            version = (prev["version"] + 1) if prev else 1
            prev_summary = json.loads(prev["summary"]) if prev and prev["summary"] else {}
            prev_summary = {k: v for k, v in prev_summary.items() if k != "warnings"}
            prev_summary["warnings"] = warnings
            cur = conn.execute(
                "INSERT INTO plans (batch_id, version, created_at, trigger, summary) VALUES (?,?,?,?,?)",
                (
                    batch_id,
                    version,
                    now_iso(),
                    "remeasure_locked",
                    json.dumps(prev_summary, ensure_ascii=False),
                ),
            )
            new_plan_id = cur.lastrowid
            if prev is not None:
                for u in conn.execute(
                    "SELECT * FROM unassigned WHERE plan_id=?", (prev["id"],)
                ).fetchall():
                    conn.execute(
                        """INSERT INTO unassigned
                           (plan_id, sample_id, name, index_seq, concentration, transfer_need, reasons)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            new_plan_id,
                            u["sample_id"],
                            u["name"],
                            u["index_seq"],
                            u["concentration"],
                            u["transfer_need"],
                            u["reasons"],
                        ),
                    )
            conn.execute(
                "INSERT INTO plan_versions (plan_id, batch_id, version, created_at, trigger, note, warnings_json) VALUES (?,?,?,?,?,?,?)",
                (
                    new_plan_id,
                    batch_id,
                    version,
                    now_iso(),
                    "remeasure_locked",
                    f"样本 {s['name']} 复测（锁定池 {locked_row['pool_no']}，配方保留）",
                    json.dumps(warnings, ensure_ascii=False),
                ),
            )
            conn.commit()
            result = get_batch(batch_id)
            result["warnings"] = warnings
            return result

        if _latest_plan(conn, batch_id) is None:
            conn.commit()
            return get_batch(batch_id)

        _plan(conn, b, trigger="remeasure", warnings=warnings, changed_sample_ids={sample_id})
        result = get_batch(batch_id)
        result["warnings"] = warnings
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------- full view

def get_batch(batch_id: int) -> dict:
    conn = connect()
    try:
        b = _get_batch(conn, batch_id)
        samples = [
            _row_to_sample(r)
            for r in conn.execute(
                "SELECT * FROM samples WHERE batch_id=? ORDER BY id", (batch_id,)
            ).fetchall()
        ]
        plan = _latest_plan(conn, batch_id)

        pools_out: list[dict] = []
        unassigned_out: list[dict] = []
        summary = None
        if plan is not None:
            sjson = json.loads(plan["summary"]) if plan["summary"] else {}
            summary = {"version": plan["version"], "created_at": plan["created_at"],
                       "trigger": plan["trigger"], **sjson}

            locked_rows = {r["id"]: r for r in conn.execute(
                "SELECT * FROM pools WHERE batch_id=? AND locked=1", (batch_id,)).fetchall()}
            for p in conn.execute(
                "SELECT * FROM pools WHERE batch_id=? ORDER BY pool_no", (batch_id,)
            ).fetchall():
                items = []
                if p["locked"] and p["recipe_json"]:
                    recipe = json.loads(p["recipe_json"])
                    for it in recipe["items"]:
                        items.append(
                            {
                                "sample_id": it["sample_id"],
                                "name": it["name"],
                                "index_seq": it["index_seq"],
                                "concentration": it["concentration_at_lock"],
                                "concentration_current": next(
                                    (x["concentration"] for x in samples if x["id"] == it["sample_id"]),
                                    None,
                                ),
                                "transfer_volume": it["transfer_volume"],
                                "target_amount": it["target_amount"],
                            }
                        )
                    total = recipe["total_volume"]
                    locked_at = recipe["locked_at"]
                else:
                    for a in conn.execute(
                        """SELECT a.*, s.name FROM assignments a JOIN samples s ON s.id=a.sample_id
                           WHERE a.pool_id=? ORDER BY a.id""",
                        (p["id"],),
                    ).fetchall():
                        items.append(
                            {
                                "sample_id": a["sample_id"],
                                "name": a["name"],
                                "index_seq": a["index_seq"],
                                "concentration": a["concentration"],
                                "concentration_current": a["concentration"],
                                "transfer_volume": a["transfer_volume"],
                                "target_amount": a["target_amount"],
                            }
                        )
                    total = round(sum(i["transfer_volume"] for i in items), 6)
                    locked_at = None
                pools_out.append(
                    {
                        "pool_no": p["pool_no"],
                        "locked": bool(p["locked"]),
                        "locked_at": locked_at,
                        "total_volume": total,
                        "items": items,
                    }
                )

            for u in conn.execute(
                "SELECT * FROM unassigned WHERE plan_id=? ORDER BY id", (plan["id"],)
            ).fetchall():
                unassigned_out.append(
                    {
                        "sample_id": u["sample_id"],
                        "name": u["name"],
                        "index_seq": u["index_seq"],
                        "concentration": u["concentration"],
                        "transfer_need": u["transfer_need"],
                        "reasons": json.loads(u["reasons"]),
                    }
                )

        versions = [
            {
                "version": r["version"],
                "created_at": r["created_at"],
                "trigger": r["trigger"],
                "note": r["note"],
                "warnings": json.loads(r["warnings_json"]),
            }
            for r in conn.execute(
                "SELECT * FROM plan_versions WHERE batch_id=? ORDER BY version DESC", (batch_id,)
            ).fetchall()
        ]

        return {
            "id": b["id"],
            "name": b["name"],
            "num_pools": b["num_pools"],
            "max_pool_volume": b["max_pool_volume"],
            "min_transfer": b["min_transfer"],
            "created_at": b["created_at"],
            "samples": samples,
            "summary": summary,
            "pools": pools_out,
            "unassigned": unassigned_out,
            "versions": versions,
        }
    finally:
        conn.close()
