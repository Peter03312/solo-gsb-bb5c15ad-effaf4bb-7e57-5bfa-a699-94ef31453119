"""CP-SAT 求解器单元测试。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.solver import SolverSample, solve_pools

C = 1_000_000  # 单池上限 100.0000（×1e4）


def s(sid, vol, idx):
    return SolverSample(id=sid, code=f"S{sid}", take_volume=int(vol * 10000), index_key=idx)


def cap(vol):
    return int(vol * 10000)


def test_all_fit_single_bin_prefers_fewer_bins():
    # 全部能装进 1 个池时，应只用 1 个池（第二目标）
    res = solve_pools([s(1, 10, "A"), s(2, 20, "B"), s(3, 30, "C")],
                      slots=[1, 2, 3], capacity=C)
    assert res.optimal
    assert len(res.unassigned) == 0
    assert res.bins_used == 1
    assert set(res.assignment.values()) == {1}  # 槽位从位置 1 开始


def test_capacity_packing_optimal():
    # 60+40 配对，两个池装下 4 个样本
    samples = [s(1, 60, "A"), s(2, 60, "B"), s(3, 40, "C"), s(4, 40, "D")]
    vols = {x.id: x.take_volume for x in samples}
    res = solve_pools(samples, slots=[1, 2, 3], capacity=cap(100))
    assert res.optimal
    assert len(res.unassigned) == 0
    assert res.bins_used == 2
    totals: dict[int, int] = {}
    for sid, slot in res.assignment.items():
        totals[slot] = totals.get(slot, 0) + vols[sid]
    for v in totals.values():
        assert v <= C


def test_duplicate_index_cannot_share_bin():
    # 同索引两个 40 体积样本：容量可同池（80<=100），但索引冲突，必须分池
    res = solve_pools([s(1, 40, "IDX1"), s(2, 40, "IDX1")],
                      slots=[1, 2], capacity=cap(100))
    assert res.optimal
    assert len(res.unassigned) == 0
    assert res.bins_used == 2
    assert res.assignment[1] != res.assignment[2]


def test_slot_limit_forces_unassigned():
    # 同索引 3 个样本，但只有 2 个槽位 => 最多安排 2 个
    res = solve_pools(
        [s(1, 40, "X"), s(2, 40, "X"), s(3, 40, "X")],
        slots=[1, 2], capacity=cap(100),
    )
    assert res.optimal
    assert len(res.assignment) == 2
    assert len(res.unassigned) == 1


def test_oversized_all_unassigned_not_fake_recipe():
    # 每个样本都超容量：不得产生任何配方
    res = solve_pools([s(1, 120, "A"), s(2, 130, "B")],
                      slots=[1, 2], capacity=cap(100))
    assert res.optimal
    assert res.assignment == {}
    assert set(res.unassigned) == {1, 2}
    assert res.bins_used == 0


def test_maximize_count_before_bin_count():
    # 容量 100：60,60,60。两槽位下最优是安排 2 个（各占一池），
    # 而不是为了少用池只安排 1 个
    res = solve_pools(
        [s(1, 60, "A"), s(2, 60, "B"), s(3, 60, "C")],
        slots=[1, 2], capacity=cap(100),
    )
    assert res.optimal
    assert len(res.assignment) == 2
    assert res.bins_used == 2


def test_no_slots():
    res = solve_pools([s(1, 10, "A")], slots=[], capacity=cap(100))
    assert res.assignment == {}
    assert res.unassigned == [1]


def test_volume_boundary_exact_capacity_fits():
    # 恰好等于容量应可装入（边界）
    res = solve_pools([s(1, 100, "A")], slots=[1], capacity=cap(100))
    assert res.assignment == {1: 1}
