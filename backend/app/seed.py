from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 直播间 (
  房间键 TEXT PRIMARY KEY,
  标题 TEXT NOT NULL,
  主播 TEXT NOT NULL,
  开播事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '直播中'
);
CREATE TABLE IF NOT EXISTS 互动事件 (
  事件编号 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  事件类型 TEXT NOT NULL,
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  观众键 TEXT NOT NULL DEFAULT '',
  点赞增量 INTEGER NOT NULL DEFAULT 0,
  送礼额 INTEGER NOT NULL DEFAULT 0,
  命运 TEXT NOT NULL DEFAULT '已入流',
  窗键 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 水位线 (
  房间键 TEXT PRIMARY KEY REFERENCES 直播间(房间键),
  事件时水位 TEXT NOT NULL,
  允许迟到秒 INTEGER NOT NULL DEFAULT 30,
  更新处理时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 热度窗 (
  窗键 TEXT PRIMARY KEY,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  窗起事件时 TEXT NOT NULL,
  窗止事件时 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '开启',
  点赞合计 INTEGER NOT NULL DEFAULT 0,
  送礼合计 INTEGER NOT NULL DEFAULT 0,
  事件笔数 INTEGER NOT NULL DEFAULT 0,
  关闭处理时 TEXT NOT NULL DEFAULT '',
  版本 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 撤回单 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  窗键 TEXT NOT NULL,
  房间键 TEXT NOT NULL,
  原因 TEXT NOT NULL,
  旧点赞 INTEGER NOT NULL,
  新点赞 INTEGER NOT NULL,
  旧送礼 INTEGER NOT NULL,
  新送礼 INTEGER NOT NULL,
  处理时 TEXT NOT NULL,
  事件编号 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 旁路匣 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 窗贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  事件数 INTEGER NOT NULL,
  已关闭窗数 INTEGER NOT NULL,
  撤回数 INTEGER NOT NULL,
  旁路数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 乱序缓冲 (
  入缓序号 INTEGER PRIMARY KEY AUTOINCREMENT,
  事件编号 TEXT NOT NULL UNIQUE,
  房间键 TEXT NOT NULL REFERENCES 直播间(房间键),
  事件时 TEXT NOT NULL,
  处理时 TEXT NOT NULL,
  入缓处理时 TEXT NOT NULL,
  入缓水位 TEXT NOT NULL,
  载荷 TEXT NOT NULL,
  批次编号 TEXT NOT NULL DEFAULT '',
  释放批次 TEXT NOT NULL DEFAULT '',
  释放处理时 TEXT NOT NULL DEFAULT '',
  排序位 INTEGER NOT NULL DEFAULT 0,
  是否处理时乱序 INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 缓冲态 (
  房间键 TEXT PRIMARY KEY REFERENCES 直播间(房间键),
  释放水位 TEXT NOT NULL DEFAULT '',
  上次释放处理时 TEXT NOT NULL DEFAULT '',
  释放批次数 INTEGER NOT NULL DEFAULT 0,
  最大处理时 TEXT NOT NULL DEFAULT '',
  最大事件时 TEXT NOT NULL DEFAULT '',
  口径 TEXT NOT NULL DEFAULT '处理时缓冲排序再推进'
);
CREATE TABLE IF NOT EXISTS 缓冲释放 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  释放批次 TEXT NOT NULL,
  房间键 TEXT NOT NULL,
  释放处理时 TEXT NOT NULL,
  水位前 TEXT NOT NULL,
  水位后 TEXT NOT NULL,
  释放事件数 INTEGER NOT NULL,
  事件编号集 TEXT NOT NULL,
  乙旁路集 TEXT NOT NULL,
  甲旁路集 TEXT NOT NULL,
  口径 TEXT NOT NULL
);
"""


站规默认 = {
    "站名": "播浪",
    "窗长秒": "60",
    "允许迟到秒": "30",
    "水位推进策略": "事件时最大值",
    "关窗条件": "水位>=窗止即关闭发射",
    "旁路条件": "水位>=窗止+允许迟到",
    "骨架": "互动事件入流→处理时乱序缓冲排序→事件时间水位线批量推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
    "乱序处理策略": "处理时缓冲排序再推进",
    "缓冲超时秒": "5",
    "缓冲批量": "4",
    "缓冲超时策略": "同房缓冲最老处理时起超过缓冲超时秒、或缓冲深度达缓冲批量、或请求冲刷时，整房释放并按事件时排序批量抬水位",
}


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def 初始化库() -> None:
    conn = 连接()
    conn.executescript(建表)
    # 补齐缺失的站规键，不覆盖已有取值
    for k, v in 站规默认.items():
        conn.execute("INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) AS c FROM 直播间").fetchone()["c"] == 0:
        conn.execute(
            "INSERT INTO 直播间(房间键, 标题, 主播, 开播事件时, 状态) VALUES (?,?,?,?,?)",
            ("房A", "晚间热聊", "主播小浪", "2026-11-22T12:00:00Z", "直播中"),
        )
        conn.execute(
            "INSERT INTO 水位线(房间键, 事件时水位, 允许迟到秒, 更新处理时) VALUES (?,?,?,?)",
            ("房A", "2026-11-22T12:00:00Z", 30, 此刻()),
        )
    conn.commit()
    conn.close()
