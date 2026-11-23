import json

from app.db import 连接
from app.seed import 此刻
from app.services import 时间, 热度窗, 乱序缓冲


def 装一批(体: dict) -> dict:
    """入流一批互动事件——乙口径：处理时缓冲、按事件时排序、批量抬水位。

    口径（全局固定）：
    - 同房事件先入「乱序缓冲」，绝不按到达序立刻抬水位；
    - 释放时按事件时升序逐条推进水位并入窗/迟到修正/旁路；
    - 缓冲释放与水位推进在同一事务内，同成败，不存在「先抬水位再丢早事件」的半截态；
    - 释放条件：冲刷 / 缓冲深度 >= 缓冲批量 / 最老缓冲处理时滞后 >= 缓冲超时秒（站规）。
    """
    批次编号 = 体.get("批次编号") or f"批-{此刻().replace(':', '').replace('-', '')}"
    事件列表 = 体.get("事件") or []
    冲刷 = bool(体.get("冲刷"))
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        报告 = {
            "批次编号": 批次编号,
            "口径": 乱序缓冲.口径,
            "入流": 0,
            "入缓": 0,
            "释放": 0,
            "入窗": 0,
            "旁路": 0,
            "撤回": 0,
            "新关窗": 0,
            "缓冲深度": 0,
            "释放明细": [],
            "明细": [],
        }
        规 = 乱序缓冲.站规(conn)
        窗长 = int(规.get("窗长秒", "60"))
        默许迟到 = int(规.get("允许迟到秒", "30"))

        请求最大处理时 = ""
        触房 = set()
        for ev in 事件列表:
            处理时 = ev.get("处理时") or 此刻()
            if not 请求最大处理时 or 时间.解析(处理时) > 时间.解析(请求最大处理时):
                请求最大处理时 = 处理时

        for ev in 事件列表:
            房间键 = ev["房间键"]
            房 = conn.execute("SELECT * FROM 直播间 WHERE 房间键=?", (房间键,)).fetchone()
            if not 房:
                conn.execute(
                    "INSERT INTO 旁路匣(原因, 载荷, 时刻) VALUES (?,?,?)",
                    ("未知直播间", json.dumps(ev, ensure_ascii=False), 此刻()),
                )
                报告["旁路"] += 1
                报告["明细"].append({"事件编号": ev.get("事件编号"), "命运": "旁路-未知房"})
                continue

            水位 = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (房间键,)).fetchone()
            if not 水位:
                conn.execute(
                    "INSERT INTO 水位线(房间键, 事件时水位, 允许迟到秒, 更新处理时) VALUES (?,?,?,?)",
                    (房间键, 房["开播事件时"], 默许迟到, 此刻()),
                )

            事件编号 = ev["事件编号"]
            处理时 = ev.get("处理时") or 此刻()

            已见 = conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号=?", (事件编号,)).fetchone()
            已在缓 = conn.execute("SELECT 1 FROM 乱序缓冲 WHERE 事件编号=?", (事件编号,)).fetchone()
            if 已见 or 已在缓:
                报告["明细"].append({"事件编号": 事件编号, "命运": "幂等跳过"})
                continue

            入缓结果 = 乱序缓冲.入缓(conn, 房间键, ev, 处理时, 批次编号)
            报告["入缓"] += 1
            触房.add(房间键)
            报告["明细"].append(
                {
                    "事件编号": 事件编号,
                    "命运": "缓冲留驻",
                    "是否处理时乱序": 入缓结果["是否处理时乱序"],
                    "入缓水位": 入缓结果["入缓水位"],
                }
            )

        # —— 释放判定：整房缓冲按事件时排序后批量推进 ——
        待释房 = set()
        if 冲刷:
            待释房 = {
                r["房间键"]
                for r in conn.execute(
                    "SELECT DISTINCT 房间键 FROM 乱序缓冲 WHERE 释放批次=''"
                )
            }
        else:
            for 房间键 in sorted(触房):
                if 乱序缓冲.需释放(conn, 房间键, 规, 请求最大处理时):
                    待释房.add(房间键)

        释序 = 0
        for 房间键 in sorted(待释房):
            释序 += 1
            释放批次 = f"{批次编号}~{房间键}~{释序}"
            结果 = 乱序缓冲.释放(
                conn, 房间键, 释放批次, 规, 窗长, int(默许迟到), 请求最大处理时
            )
            if not 结果["释放事件数"]:
                continue
            报告["释放"] += 结果["释放事件数"]
            报告["入窗"] += 结果["入窗"]
            报告["旁路"] += 结果["旁路"]
            报告["撤回"] += 结果["撤回"]
            报告["新关窗"] += 结果["新关窗"]
            报告["入流"] += 结果["入窗"]
            报告["释放明细"].append(结果)
            for d in 结果["明细"]:
                报告["明细"].append(d)
            # 该房缓冲已清空，成员明细里的「缓冲留驻」替换为最终命运
            已释编号 = {d["事件编号"] for d in 结果["明细"]}
            报告["明细"] = [
                d
                for d in 报告["明细"]
                if not (d.get("命运") == "缓冲留驻" and d.get("事件编号") in 已释编号)
            ]

        for 房行 in conn.execute("SELECT 房间键, 事件时水位, 允许迟到秒 FROM 水位线"):
            报告["新关窗"] += 热度窗.尝试关窗(
                conn, 房行["房间键"], 房行["事件时水位"], int(房行["允许迟到秒"]), 窗长, 此刻()
            )

        报告["缓冲深度"] = 乱序缓冲.缓冲深度(conn)
        报告["缓冲态"] = 乱序缓冲.读态(conn)

        conn.execute(
            "INSERT INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次编号, 此刻(), json.dumps(报告, ensure_ascii=False)),
        )
        conn.commit()
        return 报告
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
