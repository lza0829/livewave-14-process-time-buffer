"""处理时乱序缓冲（乙口径：处理时缓冲排序再推进）。

口径说明（全局只贯彻这一种）：
- 同房事件先入缓冲，绝不按「到达序」直接抬水位；
- 缓冲释放时按 **事件时升序** 逐条处理，水位随排序后的顺序推进；
- 于是「先到处理时晚事件、后到处理时早事件」在乙口径下早事件先被处理、正常入窗，
  不会被晚事件抬起来的水位误旁路；
- 释放与水位推进处于同一事务，二者同成败，不存在「已抬水位但缓冲未释放」的半截态。

只读接口见 ``读态``：缓冲深度 / 释放水位 / 旁路集（乙实际 vs 甲反事实）/ valid。
"""

import json

from app.services import 时间, 热度窗

口径 = "处理时缓冲排序再推进"


def 站规(conn) -> dict:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}


def 读水位(conn, 房间键: str):
    return conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()


def 确态(conn, 房间键: str):
    """确保该房有缓冲态行；初始释放水位取当前事件时水位。"""
    行 = conn.execute("SELECT * FROM 缓冲态 WHERE 房间键=?", (房间键,)).fetchone()
    if 行:
        return 行
    水位 = 读水位(conn, 房间键)
    起 = 水位["事件时水位"] if 水位 else ""
    conn.execute(
        """INSERT INTO 缓冲态(房间键, 释放水位, 上次释放处理时, 释放批次数, 最大处理时, 最大事件时, 口径)
           VALUES (?,?,?,?,?,?,?)""",
        (房间键, 起, "", 0, "", 起, 口径),
    )
    return conn.execute("SELECT * FROM 缓冲态 WHERE 房间键=?", (房间键,)).fetchone()


def 入缓(conn, 房间键: str, ev: dict, 处理时: str, 批次编号: str) -> dict:
    """把一条同房事件放入缓冲；此时水位不动。

    「处理时乱序」判定：该事件事件时早于本房已见最大事件时（即晚事件先到、早事件后到）。
    """
    态 = 确态(conn, 房间键)
    水位 = 读水位(conn, 房间键)
    入缓水位 = 水位["事件时水位"] if 水位 else ""
    乱序 = bool(态["最大事件时"]) and 时间.解析(ev["事件时"]) < 时间.解析(态["最大事件时"])
    conn.execute(
        """INSERT INTO 乱序缓冲(事件编号,房间键,事件时,处理时,入缓处理时,入缓水位,载荷,批次编号,是否处理时乱序)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            ev["事件编号"], 房间键, ev["事件时"], 处理时, 处理时, 入缓水位,
            json.dumps(ev, ensure_ascii=False), 批次编号, 1 if 乱序 else 0,
        ),
    )
    if not 态["最大处理时"] or 时间.解析(处理时) > 时间.解析(态["最大处理时"]):
        conn.execute("UPDATE 缓冲态 SET 最大处理时=? WHERE 房间键=?", (处理时, 房间键))
    if not 态["最大事件时"] or 时间.解析(ev["事件时"]) > 时间.解析(态["最大事件时"]):
        conn.execute("UPDATE 缓冲态 SET 最大事件时=? WHERE 房间键=?", (ev["事件时"], 房间键))
    return {"是否处理时乱序": 乱序, "入缓水位": 入缓水位}


def 缓冲深度(conn, 房间键: str = "") -> int:
    if 房间键:
        return conn.execute(
            "SELECT COUNT(*) FROM 乱序缓冲 WHERE 房间键=? AND 释放批次=''", (房间键,)
        ).fetchone()[0]
    return conn.execute("SELECT COUNT(*) FROM 乱序缓冲 WHERE 释放批次=''").fetchone()[0]


def 需释放(conn, 房间键: str, 规: dict, 当前处理时: str) -> bool:
    """站规：缓冲深度达缓冲批量，或最老缓冲处理时到当前处理时已达缓冲超时秒，即整房释放。"""
    行 = conn.execute(
        "SELECT 处理时 FROM 乱序缓冲 WHERE 房间键=? AND 释放批次=''", (房间键,)
    ).fetchall()
    if not 行:
        return False
    if len(行) >= int(规.get("缓冲批量", "4")):
        return True
    if not 当前处理时:
        return False
    最早 = min(时间.解析(r["处理时"]) for r in 行)
    return (时间.解析(当前处理时) - 最早).total_seconds() >= int(规.get("缓冲超时秒", "5"))


def 模拟甲(行列表, 水位前: str, 允许迟到秒: int, 窗长秒: int) -> list:
    """反事实：若按甲口径「到达序立即抬水位」，同一组事件会被旁路哪些。

    仅用于让两口径的旁路集合可区分；不参与主链写入。
    """
    水位 = 水位前
    旁路 = []
    for r in 行列表:  # 到达序（入缓序号）
        ev = json.loads(r["载荷"])
        时 = ev["事件时"]
        if 时间.解析(时) > 时间.解析(水位):
            水位 = 时
        窗起 = 时间.对齐窗起(时, 窗长秒)
        窗止 = 时间.加秒(窗起, 窗长秒)
        if 热度窗.已过旁路界(水位, 窗止, 允许迟到秒):
            旁路.append(ev["事件编号"])
    return 旁路


def 释放(conn, 房间键: str, 释放批次: str, 规: dict, 窗长秒: int, 允许迟到秒: int,
        触发处理时: str = "") -> dict:
    """整房释放：按事件时升序逐条推进水位、入窗/迟到修正/旁路，并留下释放履历。

    调用方须已在事务内（``BEGIN IMMEDIATE``），本函数不自行提交，
    因此「删/标记缓冲、抬水位、关窗、写事件/撤回/旁路、写履历」整体成败。
    """
    行列表 = conn.execute(
        "SELECT * FROM 乱序缓冲 WHERE 房间键=? AND 释放批次='' ORDER BY 入缓序号",
        (房间键,),
    ).fetchall()
    结果 = {
        "房间键": 房间键, "释放批次": 释放批次, "释放事件数": 0,
        "水位前": "", "水位后": "", "入窗": 0, "旁路": 0, "撤回": 0, "新关窗": 0,
        "乙旁路集": [], "甲旁路集": [], "明细": [],
    }
    if not 行列表:
        return 结果

    水位行 = 读水位(conn, 房间键)
    水位前 = 水位行["事件时水位"] if 水位行 else ""
    结果["水位前"] = 水位前
    结果["甲旁路集"] = 模拟甲(行列表, 水位前, 允许迟到秒, 窗长秒)

    释放处理时 = 触发处理时 or 时间.格式(max(时间.解析(r["处理时"]) for r in 行列表))

    排序 = sorted(行列表, key=lambda r: (时间.解析(r["事件时"]), r["入缓序号"]))
    当前水位 = 水位前
    乙旁路 = []

    for 位, r in enumerate(排序, start=1):
        ev = json.loads(r["载荷"])
        事件编号 = ev["事件编号"]
        事件时 = ev["事件时"]
        处理时 = r["处理时"]
        点赞 = int(ev.get("点赞增量") or 0)
        送礼 = int(ev.get("送礼额") or 0)
        类型 = ev.get("事件类型") or "点赞"

        # —— 水位推进：事件时升序，故只会被更早的事件推进，早事件不可能被本批晚事件误旁路 ——
        if 时间.解析(事件时) > 时间.解析(当前水位):
            当前水位 = 事件时
            conn.execute(
                "UPDATE 水位线 SET 事件时水位=?, 更新处理时=? WHERE 房间键=?",
                (当前水位, 释放处理时, 房间键),
            )
        结果["新关窗"] += 热度窗.尝试关窗(conn, 房间键, 当前水位, 允许迟到秒, 窗长秒, 释放处理时)

        conn.execute(
            "UPDATE 乱序缓冲 SET 释放批次=?, 释放处理时=?, 排序位=? WHERE 入缓序号=?",
            (释放批次, 释放处理时, 位, r["入缓序号"]),
        )

        窗起 = 时间.对齐窗起(事件时, 窗长秒)
        窗止 = 时间.加秒(窗起, 窗长秒)
        wk = 时间.窗键(房间键, 窗起)

        if 热度窗.已过旁路界(当前水位, 窗止, 允许迟到秒):
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已旁路", "", 释放批次,
                ),
            )
            conn.execute(
                "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                (
                    "超允许迟到",
                    json.dumps(
                        {
                            "事件编号": 事件编号,
                            "事件时": 事件时,
                            "窗止": 窗止,
                            "旁路界": 时间.加秒(窗止, 允许迟到秒),
                            "水位前": 水位前,
                            "水位": 当前水位,
                            "口径": 口径,
                            "依据": "释放前水位已越过窗止+允许迟到",
                        },
                        ensure_ascii=False,
                    ),
                    释放处理时,
                ),
            )
            乙旁路.append(事件编号)
            结果["旁路"] += 1
            结果["明细"].append(
                {"事件编号": 事件编号, "命运": "已旁路", "窗键本应": wk, "释放批次": 释放批次}
            )
            continue

        窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()
        if not 窗:
            conn.execute(
                """INSERT INTO 热度窗(窗键,房间键,窗起事件时,窗止事件时,状态,点赞合计,送礼合计,事件笔数,版本)
                   VALUES (?,?,?,?, '开启', 0, 0, 0, 0)""",
                (wk, 房间键, 窗起, 窗止),
            )
            窗 = conn.execute("SELECT * FROM 热度窗 WHERE 窗键=?", (wk,)).fetchone()

        if 窗["状态"] == "已关闭":
            旧赞, 旧送 = 窗["点赞合计"], 窗["送礼合计"]
            新赞, 新送 = 旧赞 + 点赞, 旧送 + 送礼
            conn.execute(
                """UPDATE 热度窗 SET 点赞合计=?, 送礼合计=?, 事件笔数=事件笔数+1, 版本=? WHERE 窗键=?""",
                (新赞, 新送, int(窗["版本"]) + 1, wk),
            )
            conn.execute(
                """INSERT INTO 撤回单(窗键,房间键,原因,旧点赞,新点赞,旧送礼,新送礼,处理时,事件编号)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (wk, 房间键, "迟到修正", 旧赞, 新赞, 旧送, 新送, 释放处理时, 事件编号),
            )
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 释放批次,
                ),
            )
            结果["入窗"] += 1
            结果["撤回"] += 1
            结果["明细"].append(
                {"事件编号": 事件编号, "命运": "迟到修正撤回", "窗键": wk, "释放批次": 释放批次}
            )
        else:
            conn.execute(
                "UPDATE 热度窗 SET 点赞合计=点赞合计+?, 送礼合计=送礼合计+?, 事件笔数=事件笔数+1 WHERE 窗键=?",
                (点赞, 送礼, wk),
            )
            conn.execute(
                """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    事件编号, 房间键, 类型, 事件时, 处理时,
                    ev.get("观众键") or "", 点赞, 送礼, "已入窗", wk, 释放批次,
                ),
            )
            结果["入窗"] += 1
            结果["明细"].append(
                {"事件编号": 事件编号, "命运": "已入窗", "窗键": wk, "释放批次": 释放批次}
            )

    conn.execute(
        """UPDATE 缓冲态 SET 释放水位=?, 上次释放处理时=?, 释放批次数=释放批次数+1
           WHERE 房间键=?""",
        (当前水位, 释放处理时, 房间键),
    )
    结果["水位后"] = 当前水位
    结果["释放事件数"] = len(行列表)
    结果["乙旁路集"] = 乙旁路
    结果["释放处理时"] = 释放处理时
    conn.execute(
        """INSERT INTO 缓冲释放(释放批次,房间键,释放处理时,水位前,水位后,释放事件数,事件编号集,乙旁路集,甲旁路集,口径)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            释放批次, 房间键, 释放处理时, 水位前, 当前水位, len(行列表),
            json.dumps([json.loads(r["载荷"])["事件编号"] for r in 排序], ensure_ascii=False),
            json.dumps(乙旁路, ensure_ascii=False),
            json.dumps(结果["甲旁路集"], ensure_ascii=False),
            口径,
        ),
    )
    return 结果


def 校验房间(conn, 房间键: str, 规: dict) -> list:
    """单房 valid 校验：缓冲/水位/旁路三者不得半截。"""
    问题 = []
    窗长 = int(规.get("窗长秒", "60"))
    允许迟到 = int(规.get("允许迟到秒", "30"))
    态 = conn.execute("SELECT * FROM 缓冲态 WHERE 房间键=?", (房间键,)).fetchone()
    水位 = 读水位(conn, 房间键)

    未释放 = conn.execute(
        "SELECT 事件编号 FROM 乱序缓冲 WHERE 房间键=? AND 释放批次=''", (房间键,)
    ).fetchall()
    未释放集 = {r["事件编号"] for r in 未释放}

    # 1) 未释放的不得已可见（禁止「缓冲未释放却已抬水位/已入窗」）
    for 编号 in 未释放集:
        已见 = conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号=?", (编号,)).fetchone()
        if 已见:
            问题.append(f"未释放事件{编号}已出现在事件表（半截）")

    # 2) 已释放的必须都能在事件表找到（禁止丢事件）
    已释放 = conn.execute(
        "SELECT 事件编号, 释放批次 FROM 乱序缓冲 WHERE 房间键=? AND 释放批次!=''", (房间键,)
    ).fetchall()
    for r in 已释放:
        已见 = conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号=?", (r["事件编号"],)).fetchone()
        if not 已见:
            问题.append(f"已释放事件{r['事件编号']}在事件表缺失（半截）")

    # 3) 有未释放缓冲时，水位不得越过上次释放水位（禁止先抬水位再等释放）
    if 未释放集 and 水位 and 态 and 态["释放水位"]:
        if 时间.解析(水位["事件时水位"]) > 时间.解析(态["释放水位"]):
            问题.append(
                f"缓冲深度{len(未释放集)}但水位{水位['事件时水位']}已越过释放水位{态['释放水位']}"
            )

    # 4) 每条旁路都必须由「释放前水位」判越界，而非本批在途水位
    旁路事件 = conn.execute(
        "SELECT 事件编号 FROM 互动事件 WHERE 房间键=? AND 命运='已旁路'", (房间键,)
    ).fetchall()
    for r in 旁路事件:
        缓 = conn.execute(
            "SELECT 释放批次, 事件时 FROM 乱序缓冲 WHERE 事件编号=?", (r["事件编号"],)
        ).fetchone()
        if not 缓 or not 缓["释放批次"]:
            问题.append(f"旁路事件{r['事件编号']}无释放履历")
            continue
        履 = conn.execute(
            "SELECT * FROM 缓冲释放 WHERE 释放批次=? AND 房间键=?", (缓["释放批次"], 房间键)
        ).fetchone()
        if not 履:
            问题.append(f"旁路事件{r['事件编号']}缺缓冲释放记录")
            continue
        窗起 = 时间.对齐窗起(缓["事件时"], 窗长)
        窗止 = 时间.加秒(窗起, 窗长)
        if not 热度窗.已过旁路界(履["水位前"], 窗止, 允许迟到):
            问题.append(
                f"旁路事件{r['事件编号']}在释放前水位{履['水位前']}下未越旁路界（口径违规）"
            )

    # 5) 事件表与缓冲释放计数一致
    for 履 in conn.execute(
        "SELECT * FROM 缓冲释放 WHERE 房间键=?", (房间键,)
    ).fetchall():
        n = conn.execute(
            "SELECT COUNT(*) FROM 乱序缓冲 WHERE 释放批次=? AND 房间键=?",
            (履["释放批次"], 房间键),
        ).fetchone()[0]
        if n != 履["释放事件数"]:
            问题.append(
                f"释放{履['释放批次']}记{履['释放事件数']}条，缓冲实际{n}条"
            )

    return 问题


def 读态(conn) -> dict:
    """乱序缓冲只读接口：缓冲深度 / 释放水位 / 旁路集（乙实际 vs 甲反事实）/ valid。"""
    规 = 站规(conn)
    房间们 = []
    for 房 in conn.execute("SELECT 房间键, 标题 FROM 直播间 ORDER BY 房间键"):
        房间键 = 房["房间键"]
        水位 = 读水位(conn, 房间键)
        态 = conn.execute("SELECT * FROM 缓冲态 WHERE 房间键=?", (房间键,)).fetchone()
        深度 = 缓冲深度(conn, 房间键)

        履历 = [dict(r) for r in conn.execute(
            "SELECT * FROM 缓冲释放 WHERE 房间键=? ORDER BY 编号 DESC LIMIT 20", (房间键,)
        )]
        乙集, 甲集 = [], []
        for h in 履历:
            try:
                乙集 += json.loads(h["乙旁路集"])
                甲集 += json.loads(h["甲旁路集"])
            except Exception:
                pass

        缓冲事件 = []
        for r in conn.execute(
            """SELECT 入缓序号, 事件编号, 事件时, 处理时, 入缓水位, 是否处理时乱序
               FROM 乱序缓冲 WHERE 房间键=? AND 释放批次='' ORDER BY 入缓序号""",
            (房间键,),
        ):
            缓冲事件.append(dict(r))

        问题 = 校验房间(conn, 房间键, 规)
        释放水位 = 态["释放水位"] if 态 and 态["释放水位"] else (水位["事件时水位"] if 水位 else "")

        房间们.append(
            {
                "房间键": 房间键,
                "标题": 房["标题"],
                "缓冲深度": 深度,
                "释放水位": 释放水位,
                "事件时水位": 水位["事件时水位"] if 水位 else "",
                "旁路集": {
                    "乙实际": 乙集,
                    "甲反事实": 甲集,
                    "差异": [x for x in 甲集 if x not in 乙集],
                },
                "valid": not 问题,
                "valid问题": 问题,
                "缓冲事件": 缓冲事件,
                "释放履历": [
                    {
                        **h,
                        "乙旁路集": json.loads(h["乙旁路集"] or "[]"),
                        "甲旁路集": json.loads(h["甲旁路集"] or "[]"),
                        "事件编号集": json.loads(h["事件编号集"] or "[]"),
                    }
                    for h in 履历
                ],
            }
        )

    总深度 = 缓冲深度(conn)
    全valid = all(r["valid"] for r in 房间们) if 房间们 else True
    return {
        "口径": 规.get("乱序处理策略", 口径),
        "策略说明": 规.get("缓冲超时策略", ""),
        "缓冲超时秒": int(规.get("缓冲超时秒", "5")),
        "缓冲批量": int(规.get("缓冲批量", "4")),
        "缓冲深度": 总深度,
        "valid": 全valid,
        "房间": 房间们,
        "时刻": None,
    }
