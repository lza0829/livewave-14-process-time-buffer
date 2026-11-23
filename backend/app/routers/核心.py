import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.seed import 此刻 as _此刻
from app.services import 装载, 贯验, 目录, 乱序缓冲


路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    冲刷: bool = False
    事件: list = Field(default_factory=list)


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "播浪",
        "骨架": "互动事件入流→事件时间水位线推进→热度窗关闭发射→迟到修正撤回→窗输出与撤回互证",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/站规")
def 站规():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
    finally:
        conn.close()


@路由.get("/直播间")
def 列直播间():
    conn = 连接()
    try:
        rooms = [dict(r) for r in conn.execute("SELECT * FROM 直播间 ORDER BY 房间键")]
        for r in rooms:
            wm = conn.execute("SELECT * FROM 水位线 WHERE 房间键=?", (r["房间键"],)).fetchone()
            r["水位线"] = dict(wm) if wm else None
        return rooms
    finally:
        conn.close()


@路由.get("/事件")
def 列事件(命运: str = ""):
    conn = 连接()
    try:
        if 命运:
            rows = conn.execute(
                "SELECT * FROM 互动事件 WHERE 命运=? ORDER BY 事件时 DESC LIMIT 200", (命运,)
            )
        else:
            rows = conn.execute("SELECT * FROM 互动事件 ORDER BY 事件时 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/水位线")
def 列水位线():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 水位线 ORDER BY 房间键")]
    finally:
        conn.close()


@路由.get("/热度窗")
def 列热度窗(状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            rows = conn.execute(
                "SELECT * FROM 热度窗 WHERE 状态=? ORDER BY 窗起事件时 DESC", (状态,)
            )
        else:
            rows = conn.execute("SELECT * FROM 热度窗 ORDER BY 窗起事件时 DESC")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/撤回单")
def 列撤回():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 撤回单 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/旁路匣")
def 列旁路():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁路匣 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


@路由.get("/批次")
def 列批次():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 装载批次 ORDER BY 时刻 DESC LIMIT 30"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d["报告"])
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.post("/装载")
def 做装载(体: 装载请求):
    return 装载.装一批(体.model_dump())


@路由.post("/装载/夹具")
def 装夹具(名: str = "准时热度样例", 冲刷: bool = False):
    路径 = 夹具目录 / f"{名}.json"
    if not 路径.exists():
        raise HTTPException(404, f"夹具不存在:{名}")
    体 = json.loads(路径.read_text(encoding="utf-8"))

    批们 = 体.get("批们")
    if isinstance(批们, list):
        报告们 = []
        for 批 in 批们:
            单 = dict(批)
            单.setdefault("冲刷", False)
            报告们.append(装载.装一批(单))
        汇总 = {
            k: sum(r.get(k, 0) for r in 报告们)
            for k in ("入缓", "释放", "入窗", "旁路", "撤回", "新关窗")
        }
        汇总["口径"] = 报告们[0]["口径"] if 报告们 else ""
        return {
            "批次编号": 体.get("批次编号", 名),
            "口径": 报告们[0]["口径"] if 报告们 else "",
            "批数": len(报告们),
            "汇总": 汇总,
            "缓冲深度": 报告们[-1]["缓冲深度"] if 报告们 else 0,
            "批次们": 报告们,
            "明细": [d for r in 报告们 for d in r["明细"]],
        }

    体["冲刷"] = 冲刷 or bool(体.get("冲刷"))
    return 装载.装一批(体)


@路由.get("/乱序缓冲")
def 取乱序缓冲():
    conn = 连接()
    try:
        态 = 乱序缓冲.读态(conn)
        态["时刻"] = _此刻()
        return 态
    finally:
        conn.close()


@路由.get("/缓冲释放")
def 列缓冲释放():
    conn = 连接()
    try:
        out = []
        for r in conn.execute("SELECT * FROM 缓冲释放 ORDER BY 编号 DESC LIMIT 100"):
            d = dict(r)
            for k in ("事件编号集", "乙旁路集", "甲旁路集"):
                try:
                    d[k] = json.loads(d[k] or "[]")
                except Exception:
                    pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.post("/贯验")
def 做贯验():
    return 贯验.跑贯验()


@路由.get("/贯验")
def 列贯验():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 窗贯验 ORDER BY 编号 DESC LIMIT 20")]
    finally:
        conn.close()


@路由.get("/空桩")
def 空桩():
    from app import modules

    return modules.列表()
