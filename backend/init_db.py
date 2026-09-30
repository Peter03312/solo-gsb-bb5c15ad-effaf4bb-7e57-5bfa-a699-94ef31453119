"""Initialize the SQLite database. Runs at container start and can be run manually."""
from app.db import init_db

if __name__ == "__main__":
    init_db()
    print("数据库初始化完成")
