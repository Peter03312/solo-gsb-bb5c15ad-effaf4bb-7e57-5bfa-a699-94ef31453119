"""API 全流程测试。"""
from .conftest import PLAN, make_sample


def create(client, samples, **overrides):
    payload = {**PLAN, "samples": samples, **overrides}
    r = client.post("/api/experiments", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- 输入校验

def test_reject_non_positive(client):
    bad = make_sample("S1", 0, 10, 5, "ACGT")
    r = client.post("/api/experiments", json={**PLAN, "samples": [bad]})
    assert r.status_code == 422

    bad2 = make_sample("S1", 2, -3, 5, "ACGT")
    r = client.post("/api/experiments", json={**PLAN, "samples": [bad2]})
    assert r.status_code == 422

    r = client.post("/api/experiments", json={
        **PLAN, "available_pools": 0,
        "samples": [make_sample("S1", 2, 10, 5, "ACGT")],
    })
    assert r.status_code == 422


def test_reject_empty_index(client):
    r = client.post("/api/experiments", json={
        **PLAN,
        "samples": [make_sample("S1", 2, 10, 5, "  ")],
    })
    assert r.status_code == 422


def test_reject_duplicate_code(client):
    r = client.post("/api/experiments", json={
        **PLAN,
        "samples": [
            make_sample("S1", 2, 10, 5, "ACGT"),
            make_sample("S1", 2, 10, 5, "TTTT"),
        ],
    })
    assert r.status_code == 422


def test_reject_min_pipette_gt_capacity(client):
    r = client.post("/api/experiments", json={
        **PLAN, "min_pipette_volume": "150",
        "samples": [make_sample("S1", 2, 10, 5, "ACGT")],
    })
    assert r.status_code == 422


# ---------------------------------------------------------------- 基本排池

def test_take_volume_is_dose_div_conc(client):
    data = create(client, [make_sample("S1", 4, 20, 10, "ACGT")])
    pool = data["pools"][0]
    # 10 / 4 = 2.5
    assert pool["assignments"][0]["take_volume"] == "2.5000"
    assert pool["total_volume"] == "2.5000"
    assert data["unarranged"] == []


def test_duplicate_index_separated(client):
    samples = [
        make_sample("S1", 1, 100, 40, "ACGTACGT"),
        make_sample("S2", 1, 100, 40, "ACGTACGT"),
    ]
    data = create(client, samples, pool_capacity="100")
    assert len(data["pools"]) == 2
    assert data["current_version"] == 1


def test_infeasible_sample_has_reason_no_fake_recipe(client):
    # 取液量 10/0.1 = 100 > 可用体积 50 => 不可行，不得进任何池
    samples = [make_sample("S1", "0.1", 50, 10, "ACGT")]
    data = create(client, samples, pool_capacity="1000")
    assert data["pools"] == []
    assert len(data["unarranged"]) == 1
    u = data["unarranged"][0]
    assert u["status"] == "unarranged"
    assert "可用体积" in u["reason"]


def test_below_pipette_min_reason(client):
    # 1 / 100 = 0.01 < 移液下限 1
    samples = [make_sample("S1", 100, 1000, 1, "ACGT")]
    data = create(client, samples, min_pipette_volume="1", pool_capacity="1000")
    assert data["pools"] == []
    assert "移液量下限" in data["unarranged"][0]["reason"]


def test_pool_capacity_enforced(client):
    # 两个 60 体积样本，容量 100 => 分两个池
    samples = [
        make_sample("S1", 1, 1000, 60, "AAAA"),
        make_sample("S2", 1, 1000, 60, "CCCC"),
    ]
    data = create(client, samples, pool_capacity="100", available_pools=3)
    assert len(data["pools"]) == 2
    for p in data["pools"]:
        assert float(p["total_volume"]) <= 100


def test_slots_exhausted_unassigned_reason(client):
    # 同索引 3 个样本，仅 2 个池 => 1 个未安排且带原因
    samples = [
        make_sample("S1", 1, 1000, 40, "TTTT"),
        make_sample("S2", 1, 1000, 40, "TTTT"),
        make_sample("S3", 1, 1000, 40, "TTTT"),
    ]
    data = create(client, samples, pool_capacity="100", available_pools=2)
    assert len(data["pools"]) == 2
    assert len(data["unarranged"]) == 1
    assert "池数" in data["unarranged"][0]["reason"] or "索引" in data["unarranged"][0]["reason"]


# ---------------------------------------------------------------- 锁定与复测

def _three(client, **kw):
    samples = [
        make_sample("S1", 1, 1000, 40, "AAAA"),
        make_sample("S2", 1, 1000, 40, "CCCC"),
        make_sample("S3", 1, 1000, 40, "GGGG"),
    ]
    return create(client, samples, pool_capacity="200", available_pools=3, **kw)


def test_lock_keeps_recipe_on_remeasure(client):
    data = _three(client)
    # 40+40=80 三个样本可同池（索引各异）
    assert len(data["pools"]) == 1
    pool_pos = data["pools"][0]["position"]
    before = {a["code"]: a["take_volume"] for a in data["pools"][0]["assignments"]}

    # 锁定池 1
    r = client.post(f"/api/experiments/{data['id']}/pools/{pool_pos}/lock?locked=true")
    assert r.status_code == 200

    # 复测 S1：浓度从 1 变 2，新取液量应为 20
    r = client.post(f"/api/experiments/{data['id']}/remeasure", json={
        "updates": [{"sample_id": data["samples"][0]["id"], "concentration": "2"}]
    })
    assert r.status_code == 200, r.text
    after = r.json()
    locked = next(p for p in after["pools"] if p["position"] == pool_pos)
    assert locked["locked"] is True
    after_map = {a["code"]: a["take_volume"] for a in locked["assignments"]}
    # 原配方保留
    assert after_map == before
    # 受影响警示
    joined = " ".join(locked["warnings"])
    assert "S1" in joined and "20" in joined
    # 版本记录增加
    assert after["current_version"] == 2
    assert [v["version_no"] for v in after["versions"]] == [1, 2]


def test_unlocked_pool_recomputed_after_remeasure(client):
    samples = [
        make_sample("S1", 1, 1000, 40, "AAAA"),
        make_sample("S2", 1, 1000, 40, "CCCC"),
    ]
    data = create(client, samples, pool_capacity="100")
    s1 = data["samples"][0]["id"]

    # 复测 S1 浓度 0.5 => 取液量 80；与 S2(40) 合计 120 > 100 => 拆成两池
    r = client.post(f"/api/experiments/{data['id']}/remeasure", json={
        "updates": [{"sample_id": s1, "concentration": "0.5"}]
    })
    assert r.status_code == 200
    after = r.json()
    assert len(after["pools"]) == 2
    assert after["pools"][0]["locked"] is False


def test_remeasure_rejects_non_positive(client):
    data = _three(client)
    r = client.post(f"/api/experiments/{data['id']}/remeasure", json={
        "updates": [{"sample_id": data["samples"][0]["id"], "concentration": "0"}]
    })
    assert r.status_code == 422


def test_add_samples_triggers_recompute(client):
    data = _three(client)
    r = client.post(f"/api/experiments/{data['id']}/samples", json={
        "samples": [make_sample("S4", 1, 1000, 40, "AAAA")]
    })
    assert r.status_code == 201, r.text
    after = r.json()
    # S4 与 S1 同索引 A，不能同池，会出现第二个池
    positions = {(a["code"], p["position"]) for p in after["pools"] for a in p["assignments"]}
    s1_pool = next(pos for code, pos in positions if code == "S1")
    s4_pool = next(pos for code, pos in positions if code == "S4")
    assert s1_pool != s4_pool


def test_version_snapshot_endpoint(client):
    data = _three(client)
    r = client.get(f"/api/experiments/{data['id']}/versions/1")
    assert r.status_code == 200
    snap = r.json()["snapshot"]
    assert snap["version_no"] == 1
    assert len(snap["pools"]) == 1
    assert snap["pools"][0]["members"][0]["take_volume"] == "40.0000"


def test_list_and_delete(client):
    data = _three(client)
    r = client.get("/api/experiments")
    assert r.status_code == 200
    assert len(r.json()) == 1
    r = client.delete(f"/api/experiments/{data['id']}")
    assert r.status_code == 204
    r = client.get(f"/api/experiments/{data['id']}")
    assert r.status_code == 404


def test_404_for_missing_experiment(client):
    assert client.get("/api/experiments/999").status_code == 404
