import json

from app.db import 连接
from app.seed import 此刻
from app.services import 乱序缓冲


def 跑贯验() -> dict:
    """窗输出与撤回互证，并覆盖处理时乱序缓冲的「不得半截」。

    - 已关闭窗的点赞/送礼/笔数 = 落入该窗的事件合计；末次撤回的新值须与窗表一致；
    - 旁路事件不得挂窗键；
    - 缓冲 valid：未释放事件不得已可见、已释放事件不得缺失、有缓冲时水位不得越过释放水位；
    - 每条旁路须由「释放前水位」判定越界（乙口径），而非本批在途水位；
    - 两口径旁路集可区分：甲反事实旁路集须记录且与乙实际集并列。
    """
    conn = 连接()
    try:
        问题 = []
        事件数 = conn.execute("SELECT COUNT(*) FROM 互动事件").fetchone()[0]
        已关闭 = conn.execute("SELECT * FROM 热度窗 WHERE 状态='已关闭'").fetchall()
        撤回数 = conn.execute("SELECT COUNT(*) FROM 撤回单").fetchone()[0]
        旁路数 = conn.execute("SELECT COUNT(*) FROM 旁路匣").fetchone()[0]

        for 窗 in 已关闭:
            agg = conn.execute(
                """SELECT COALESCE(SUM(点赞增量),0) AS 赞, COALESCE(SUM(送礼额),0) AS 送, COUNT(*) AS n
                   FROM 互动事件 WHERE 窗键=? AND 命运='已入窗'""",
                (窗["窗键"],),
            ).fetchone()
            if agg["赞"] != 窗["点赞合计"] or agg["送"] != 窗["送礼合计"]:
                问题.append(
                    f"窗{窗['窗键']}合计不符: 窗表赞{窗['点赞合计']}/送{窗['送礼合计']} vs 事件赞{agg['赞']}/送{agg['送']}"
                )
            if agg["n"] != 窗["事件笔数"]:
                问题.append(f"窗{窗['窗键']}笔数不符: 窗表{窗['事件笔数']} vs 事件{agg['n']}")

            末撤 = conn.execute(
                "SELECT * FROM 撤回单 WHERE 窗键=? ORDER BY 编号 DESC LIMIT 1",
                (窗["窗键"],),
            ).fetchone()
            if 末撤 and (末撤["新点赞"] != 窗["点赞合计"] or 末撤["新送礼"] != 窗["送礼合计"]):
                问题.append(f"窗{窗['窗键']}末次撤回与窗表不一致")

        # 旁路事件不得挂窗键
        脏旁路 = conn.execute(
            "SELECT COUNT(*) FROM 互动事件 WHERE 命运='已旁路' AND 窗键!=''"
        ).fetchone()[0]
        if 脏旁路:
            问题.append(f"旁路事件仍挂窗键:{脏旁路}")

        # —— 处理时乱序缓冲协同校验 ——
        规 = 乱序缓冲.站规(conn)
        缓冲深度 = 乱序缓冲.缓冲深度(conn)
        释放批次数 = conn.execute("SELECT COUNT(*) FROM 缓冲释放").fetchone()[0]
        for 房 in conn.execute("SELECT 房间键 FROM 直播间 ORDER BY 房间键"):
            问题.extend(乱序缓冲.校验房间(conn, 房["房间键"], 规))

        # 两口径旁路集须可区分（每条释放履历都留了甲反事实集与乙实际集）
        缺反事实 = conn.execute(
            "SELECT COUNT(*) FROM 缓冲释放 WHERE 甲旁路集 IS NULL OR 甲旁路集=''"
        ).fetchone()[0]
        if 缺反事实:
            问题.append(f"缓冲释放缺甲反事实旁路集:{缺反事实}")

        通过 = 1 if not 问题 else 0
        说明 = "窗输出与事件/撤回/乱序缓冲互证通过" if 通过 else "；".join(问题)[:800]
        conn.execute(
            """INSERT INTO 窗贯验(时刻,事件数,已关闭窗数,撤回数,旁路数,是否通过,说明)
               VALUES (?,?,?,?,?,?,?)""",
            (此刻(), 事件数, len(已关闭), 撤回数, 旁路数, 通过, 说明),
        )
        conn.commit()
        return {
            "是否通过": bool(通过),
            "事件数": 事件数,
            "已关闭窗数": len(已关闭),
            "撤回数": 撤回数,
            "旁路数": 旁路数,
            "缓冲深度": 缓冲深度,
            "缓冲释放批次数": 释放批次数,
            "说明": 说明,
            "问题": 问题,
        }
    finally:
        conn.close()
