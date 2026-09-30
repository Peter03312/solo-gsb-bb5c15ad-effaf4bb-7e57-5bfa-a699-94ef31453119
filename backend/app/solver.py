"""拼池求解器。

问题：把样本装入若干个池，每个池
  * 总取液量 <= 单池体积上限 capacity；
  * 同池内索引序列不得重复；
  * 池的数量不超过空闲槽位数；
  * 取液量固定（投料量 ÷ 浓度），不可拆分。

优化目标（严格字典序）：
  1. 安排下的样本数最多；
  2. 在样本数最多的前提下，使用的池数最少。

使用 OR-Tools CP-SAT，分两阶段求解以更高效地证明最优：
阶段一最大化安排数并固定之，阶段二最小化使用池数。
"""
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

from .config import SOLVER_TIME_LIMIT


@dataclass
class SolverSample:
    id: int
    code: str
    take_volume: int  # 已按 10^4 缩放为整数
    index_key: str


@dataclass
class SolveResult:
    assignment: dict[int, int] = field(default_factory=dict)  # sample_id -> 槽位号
    unassigned: list[int] = field(default_factory=list)
    bins_used: int = 0
    optimal: bool = False
    # feasible: 找到满足全部硬约束的最佳可行解；infeasible/unknown: 求解器失败
    status: str = "feasible"


def _build_base_model(samples: list[SolverSample], slots: list[int], capacity: int):
    """构造公共的约束模型，返回 (model, x, u)。"""
    model = cp_model.CpModel()
    n, b = len(samples), len(slots)

    # x[i,j]: 样本 i 放入槽位 j
    x = {
        (i, j): model.NewBoolVar(f"x_{samples[i].id}_{j}")
        for i in range(n)
        for j in range(b)
    }
    # u[j]: 槽位 j 是否被使用
    u = [model.NewBoolVar(f"u_{j}") for j in range(b)]

    # 每个样本至多放入一个池（也可以不安排）
    for i in range(n):
        model.AddAtMostOne(x[i, j] for j in range(b))

    for j in range(b):
        in_bin = [x[i, j] for i in range(n)]
        # 容量约束：只要槽位被使用，装入体积之和不得超过上限
        model.Add(
            sum(samples[i].take_volume * x[i, j] for i in range(n)) <= capacity
        ).OnlyEnforceIf(u[j])
        # 空槽位（u=0）里不能有样本；非空槽位必须 u=1
        model.Add(sum(in_bin) == 0).OnlyEnforceIf(u[j].Not())
        model.Add(sum(in_bin) >= 1).OnlyEnforceIf(u[j])

    # 同池索引不得重复：同一索引组在任一池中的成员数 <= 1
    # （线性上界比对偶禁止对更强、约束数更少）
    by_index: dict[str, list[int]] = {}
    for i, s in enumerate(samples):
        by_index.setdefault(s.index_key, []).append(i)
    for members in by_index.values():
        if len(members) < 2:
            continue
        for j in range(b):
            model.Add(sum(x[i, j] for i in members) <= 1)

    # 槽位对称破除：使用状态单调不增，消除“同一方案、池号互换”的等价解
    for j in range(b - 1):
        model.Add(u[j] >= u[j + 1])

    return model, x, u


def _solver(time_limit: float | None = None):
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit or SOLVER_TIME_LIMIT
    s.parameters.num_search_workers = 8
    s.parameters.linearization_level = 2
    return s


def _extract(solver, samples, slots, x, u, status) -> SolveResult:
    result = SolveResult()
    result.optimal = status == cp_model.OPTIMAL
    result.status = "optimal" if result.optimal else "feasible"
    for i, smp in enumerate(samples):
        placed = False
        for j, slot in enumerate(slots):
            if solver.Value(x[i, j]) == 1:
                result.assignment[smp.id] = slot
                placed = True
                break
        if not placed:
            result.unassigned.append(smp.id)
    result.bins_used = sum(int(solver.Value(uj)) for uj in u)
    return result


def solve_pools(
    samples: list[SolverSample],
    slots: list[int],
    capacity: int,
) -> SolveResult:
    """求解。slots 为可用（未锁定的）池槽位号列表，长度即池数上限。"""
    result = SolveResult()
    if not samples:
        result.optimal = True
        result.status = "optimal"
        return result
    if not slots:
        # 没有可用槽位：所有样本都无法安排，绝不生成配方
        result.optimal = True
        result.status = "optimal"
        result.unassigned = [s.id for s in samples]
        return result

    b = len(slots)
    # 两阶段平分总求解预算（每阶段至少 5 秒）
    phase_limit = max(5.0, SOLVER_TIME_LIMIT / 2)

    # ---------- 阶段一：最大化安排样本数 ----------
    m1, x1, u1 = _build_base_model(samples, slots, capacity)
    count1 = sum(x1[i, j] for i in range(len(samples)) for j in range(b))
    m1.Maximize(count1)
    solver1 = _solver(phase_limit)
    st1 = solver1.Solve(m1)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 理论上空解恒可行；走到这里说明求解器异常
        result.optimal = False
        result.status = "unknown"
        result.unassigned = [s.id for s in samples]
        return result

    best_count = int(round(solver1.ObjectiveValue()))
    phase1_optimal = st1 == cp_model.OPTIMAL

    # ---------- 阶段二：固定安排数，最小化使用池数 ----------
    m2, x2, u2 = _build_base_model(samples, slots, capacity)
    count2 = sum(x2[i, j] for i in range(len(samples)) for j in range(b))
    m2.Add(count2 == best_count)
    bins2 = sum(u2)
    m2.Minimize(bins2)
    solver2 = _solver(phase_limit)
    st2 = solver2.Solve(m2)
    if st2 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        # 退化：阶段一至少有可行解
        return _extract(solver1, samples, slots, x1, u1, st1)

    result = _extract(solver2, samples, slots, x2, u2, st2)
    # 只有两个阶段都证明最优，才标记为最优
    result.optimal = phase1_optimal and st2 == cp_model.OPTIMAL
    return result
