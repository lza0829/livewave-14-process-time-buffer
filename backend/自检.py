"""处理时乱序缓冲自检：不起服务，直接驱动服务层。

用法（在 backend 目录）：
    python 自检.py

会使用临时数据目录，不污染 backend/data。覆盖：
1. 先到处理时晚事件、后到处理时早事件——乙口径下早事件入窗，甲反事实集里它被误旁路；
2. 缓冲释放与关窗并发——释放/关窗/水位推进同成败，不得半截；
3. 释放中途失败——整批回滚，不留半截；
4. 窗互证（含缓冲 valid）通过。
"""

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="播浪自检-")
os.environ["数据目录"] = _tmp
os.environ.setdefault(
    "夹具目录", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures")
)

from app import seed  # noqa: E402
from app.db import 夹具目录, 连接  # noqa: E402
from app.services import 装载, 贯验, 乱序缓冲  # noqa: E402
import json  # noqa: E402

失败 = []


def 断言(条件, 说明):
    print(("  ✓ " if 条件 else "  ✗ ") + 说明)
    if not 条件:
        失败.append(说明)


def 装夹具(名: str, 冲刷: bool = True):
    体 = json.loads((夹具目录 / f"{名}.json").read_text(encoding="utf-8"))
    体["冲刷"] = 冲刷
    return 装载.装一批(体)


def main() -> int:
    seed.初始化库()

    print("\n[1] 处理时乱序：晚事件先到、早事件后到（乙口径）")
    报 = 装夹具("处理时乱序样例")
    事件 = {r["事件编号"]: dict(r) for r in 连接().execute("SELECT * FROM 互动事件")}
    断言(事件["O2-早后到"]["命运"] == "已入窗", "早事件入窗而非旁路")
    断言(事件["O1-晚先到"]["命运"] == "已入窗", "晚事件同样入窗")
    态 = 乱序缓冲.读态(连接())
    房 = next(r for r in 态["房间"] if r["房间键"] == "房A")
    断言(房["旁路集"]["乙实际"] == [], "乙实际旁路集为空")
    断言("O2-早后到" in 房["旁路集"]["甲反事实"], "甲反事实集里早事件会被误旁路")
    断言(房["旁路集"]["差异"] == ["O2-早后到"], "两口径旁路集可区分")
    断言(房["valid"], "缓冲 valid")

    print("\n[2] 缓冲释放 × 关窗并发：不得半截")
    for 名 in ("准时热度样例", "迟到修正样例", "超迟到旁路样例", "缓冲释放关窗并发样例"):
        报 = 装夹具(名)
        取报 = 报.get("汇总") or 报
        断言(报.get("缓冲深度", 0) == 0, f"{名}：本批缓冲已清空")
        断言(取报.get("释放", 0) == 取报.get("入缓", 0), f"{名}：入缓数=释放数")
    果 = 贯验.跑贯验()
    断言(果["是否通过"], "窗互证通过：" + 果["说明"])
    断言(果["缓冲深度"] == 0, "互证时缓冲深度为 0")

    print("\n[3] 释放中途失败：整体回滚，不留半截")
    conn = 连接()
    conn.execute(
        """INSERT INTO 互动事件(事件编号,房间键,事件类型,事件时,处理时,观众键,点赞增量,送礼额,命运,窗键,批次编号)
           VALUES ('KEEP','房A','点赞','2026-11-22T12:06:10Z','2026-11-22T12:06:11Z','观',1,0,'已入窗','房A|2026-11-22T12:06:00Z','手动')"""
    )
    conn.commit()
    水位前 = conn.execute("SELECT 事件时水位 FROM 水位线 WHERE 房间键='房A'").fetchone()[0]
    conn.close()

    原 = 乱序缓冲.热度窗.尝试关窗
    乱序缓冲.热度窗.尝试关窗 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("注入失败"))
    try:
        装载.装一批(
            {
                "批次编号": "注入失败批",
                "冲刷": True,
                "事件": [
                    {
                        "事件编号": "K1",
                        "房间键": "房A",
                        "事件类型": "点赞",
                        "事件时": "2026-11-22T12:06:40Z",
                        "处理时": "2026-11-22T12:06:41Z",
                        "观众键": "观",
                        "点赞增量": 1,
                        "送礼额": 0,
                    }
                ],
            }
        )
        断言(False, "异常应被抛出")
    except RuntimeError:
        断言(True, "异常已抛出")
    finally:
        乱序缓冲.热度窗.尝试关窗 = 原

    conn = 连接()
    缓冲数 = conn.execute("SELECT COUNT(*) FROM 乱序缓冲 WHERE 释放批次=''").fetchone()[0]
    已见K1 = conn.execute("SELECT 1 FROM 互动事件 WHERE 事件编号='K1'").fetchone()
    水位后 = conn.execute("SELECT 事件时水位 FROM 水位线 WHERE 房间键='房A'").fetchone()[0]
    批数 = conn.execute("SELECT COUNT(*) FROM 装载批次 WHERE 编号='注入失败批'").fetchone()[0]
    conn.close()
    断言(缓冲数 == 0, "失败批未留下未释放缓冲")
    断言(已见K1 is None, "失败批事件未落事件表")
    断言(水位后 == 水位前, "失败批未推进水位")
    断言(批数 == 0, "失败批未记录装载批次")

    print("\n[4] 终态互证")
    果 = 贯验.跑贯验()
    断言(果["是否通过"], "终态窗互证通过：" + 果["说明"])

    print("\n结果：" + ("全部通过" if not 失败 else f"{len(失败)} 项失败"))
    return 0 if not 失败 else 1


if __name__ == "__main__":
    sys.exit(main())
