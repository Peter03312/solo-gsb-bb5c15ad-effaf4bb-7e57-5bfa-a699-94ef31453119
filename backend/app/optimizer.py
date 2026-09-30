"""Optimal pool assignment via mixed-integer linear programming.

Model
-----
For each sample *s* that can individually satisfy the transfer rules, and each
of the ``num_pools`` available pools *p*, a binary variable ``x[s,p]`` is 1
when sample *s* is placed in pool *p*.

* Each candidate sample is placed in at most one pool.
* A pool's total transfer volume never exceeds ``max_pool_volume``.
* Two samples sharing the same index sequence never share a pool.
* ``y[p]`` is 1 when pool *p* is used; ``y[p] <= sum_s x[s,p]`` and
  ``x[s,p] <= y[p]``.

The objective lexicographically maximises the number of placed samples and
then minimises the number of used pools:
``-BIG * placed + used``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

# Placing one more sample always outweighs any possible pool saving.
BIG = 1_000_000
TOL = 1e-7


class OptimizerError(RuntimeError):
    """Raised when the MILP solver fails to produce a solution."""


@dataclass
class Sample:
    sid: int
    name: str
    index_seq: str
    concentration: float
    transfer_need: float  # target_amount / concentration


@dataclass
class PoolResult:
    pool_no: int  # 1-based, among available pool positions
    samples: list[dict] = field(default_factory=list)
    total_volume: float = 0.0


@dataclass
class OptimizeResult:
    pools: list[PoolResult]
    placed_ids: set[int]
    candidate_ids: list[int]


def solve(
    samples: list[Sample],
    num_pools: int,
    max_pool_volume: float,
) -> OptimizeResult:
    """Assign samples to pools. Caller guarantees samples are individually feasible."""
    n = len(samples)
    K = int(num_pools)
    if n == 0 or K == 0:
        return OptimizeResult(pools=[], placed_ids=set(), candidate_ids=[smp.sid for smp in samples])

    # Variable layout: x[0..n*K-1] row-major (sample s -> s*K + p), y[K]
    nv = n * K + K

    rows, cols, vals = [], [], []
    row_idx = 0

    def add(coefs: dict[int, float]):
        nonlocal row_idx
        for j, v in coefs.items():
            rows.append(row_idx)
            cols.append(j)
            vals.append(v)
        row_idx += 1

    lb: list[float] = []
    ub: list[float] = []

    # 1) each sample at most one pool
    for s in range(n):
        add({s * K + p: 1.0 for p in range(K)})
        lb.append(0.0)
        ub.append(1.0)

    # 2) capacity + at-most-one per index in each pool
    index_groups: dict[str, list[int]] = {}
    for s, smp in enumerate(samples):
        index_groups.setdefault(smp.index_seq, []).append(s)

    for p in range(K):
        add({s * K + p: samples[s].transfer_need for s in range(n)})
        lb.append(-np.inf)
        ub.append(float(max_pool_volume) + TOL)
        for group in index_groups.values():
            if len(group) < 2:
                continue
            add({s * K + p: 1.0 for s in group})
            lb.append(-np.inf)
            ub.append(1.0)

    def yidx(p: int) -> int:
        return n * K + p

    # 3) x[s,p] <= y[p]
    for s in range(n):
        for p in range(K):
            add({s * K + p: 1.0, yidx(p): -1.0})
            lb.append(-np.inf)
            ub.append(0.0)

    # 4) y[p] <= sum_s x[s,p]
    for p in range(K):
        coefs = {yidx(p): 1.0}
        coefs.update({s * K + p: -1.0 for s in range(n)})
        add(coefs)
        lb.append(-np.inf)
        ub.append(0.0)

    A = coo_matrix((vals, (rows, cols)), shape=(len(lb), nv)).tocsr()

    c = np.zeros(nv)
    c[: n * K] = -float(BIG)
    c[n * K:] = 1.0

    integrality = np.ones(nv)
    bounds = Bounds(lb=0, ub=1)
    result = milp(
        c=c,
        integrality=integrality,
        bounds=bounds,
        constraints=LinearConstraint(A, np.array(lb), np.array(ub)),
        options={"disp": False, "time_limit": 60},
    )
    if not result.success or result.x is None:
        raise OptimizerError(f"求解器未能给出方案: {result.message}")

    x = result.x[: n * K].reshape(n, K)
    placements: dict[int, int] = {}
    for s in range(n):
        p = int(np.argmax(x[s]))
        if x[s, p] > 0.5:
            placements[s] = p

    # Compact the used bin positions to 0..m-1 so pool numbers are contiguous.
    used_positions = sorted(set(placements.values()))
    remap = {old: new for new, old in enumerate(used_positions)}

    pools: dict[int, PoolResult] = {}
    for s, p in placements.items():
        smp = samples[s]
        new_p = remap[p]
        pr = pools.setdefault(new_p, PoolResult(pool_no=new_p + 1))
        pr.samples.append(
            {
                "sample_id": smp.sid,
                "name": smp.name,
                "index_seq": smp.index_seq,
                "concentration": smp.concentration,
                "transfer_volume": round(smp.transfer_need, 6),
                "target_amount": round(smp.transfer_need * smp.concentration, 6),
            }
        )
        pr.total_volume = round(pr.total_volume + smp.transfer_need, 6)

    ordered = [pools[p] for p in sorted(pools)]
    _verify(ordered, max_pool_volume, index_groups)
    return OptimizeResult(
        pools=ordered,
        placed_ids={samples[s].sid for s in placements},
        candidate_ids=[smp.sid for smp in samples],
    )


def _verify(pools: list[PoolResult], max_pool_volume: float, index_groups: dict[str, list[int]]) -> None:
    """Defensive check: never emit a recipe that violates a hard constraint."""
    for pr in pools:
        if pr.total_volume > max_pool_volume + 1e-6:
            raise OptimizerError(f"池 {pr.pool_no} 超出单池体积上限")
        seen: set[str] = set()
        for item in pr.samples:
            if item["index_seq"] in seen:
                raise OptimizerError(f"池 {pr.pool_no} 出现重复索引 {item['index_seq']}")
            seen.add(item["index_seq"])
