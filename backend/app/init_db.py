"""显式初始化数据库（建表）。容器启动时由 entrypoint 调用，幂等。"""
from .database import Base, engine
from . import models  # noqa: F401  注册模型元数据


def main() -> None:
    Base.metadata.create_all(bind=engine)
    print("数据库初始化完成")


if __name__ == "__main__":
    main()
