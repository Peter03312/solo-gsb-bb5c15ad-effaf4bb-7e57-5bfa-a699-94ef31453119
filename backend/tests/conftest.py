import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# 在导入应用模块前指定默认数据库（database.py 导入时会创建目录）
os.environ.setdefault("SQLALCHEMY_URL", "sqlite:////tmp/pooling_test_default.db")
os.environ.setdefault("SOLVER_TIME_LIMIT", "10")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    from app import models  # noqa: F401 注册元数据
    from app.database import Base, get_db
    from app.main import app
    from fastapi.testclient import TestClient

    Base.metadata.create_all(bind=engine)

    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db

    # 启动事件会用默认引擎建表，忽略其结果；测试数据全部走覆盖会话
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_sample(code, conc, vol, dose, idx):
    return {
        "code": code,
        "concentration": str(conc),
        "available_volume": str(vol),
        "target_dose": str(dose),
        "index_sequence": idx,
    }


PLAN = dict(
    name="测试计划",
    available_pools=3,
    pool_capacity="100",
    min_pipette_volume="1",
)
