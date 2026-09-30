"""SQLAlchemy 引擎与会话。"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import SQLALCHEMY_URL

# 确保 SQLite 文件所在目录存在
if SQLALCHEMY_URL.startswith("sqlite:///"):
    db_path = SQLALCHEMY_URL.replace("sqlite:///", "", 1)
    if db_path and db_path != ":memory:":
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

connect_args = {"check_same_thread": False} if SQLALCHEMY_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_URL, connect_args=connect_args, future=True)

if SQLALCHEMY_URL.startswith("sqlite"):
    # SQLite 开启外键约束，保证级联删除生效
    @event.listens_for(engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖：每请求一个会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
