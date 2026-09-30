"""全局配置（可通过环境变量覆盖）。"""
import os

# SQLite 数据库文件位置：容器内默认 /data/pooling.db，可用 SQLALCHEMY_URL 覆盖
DEFAULT_DB_PATH = os.environ.get("DB_PATH", "/data/pooling.db")
SQLALCHEMY_URL = os.environ.get(
    "SQLALCHEMY_URL", f"sqlite:///{DEFAULT_DB_PATH}"
)

# 体积/质量计算保留的小数位
VOLUME_DECIMALS = 4
# 浓度保留的小数位
CONC_DECIMALS = 6
# CP-SAT 最长求解时间（秒）
SOLVER_TIME_LIMIT = float(os.environ.get("SOLVER_TIME_LIMIT", "30"))
