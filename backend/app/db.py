import os
import sqlite3
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "播浪.db"


def 连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    # 缓冲释放与水位推进同事务；并发装载时串行等待而非报「database is locked」
    c.execute("PRAGMA busy_timeout = 15000")
    try:
        c.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    return c
