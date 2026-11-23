import React, { useEffect, useState } from "react";
import { 取 } from "../api.js";

export default function 乱序缓冲页() {
  const [态, 设] = useState(null);
  const 刷 = () => 取("/乱序缓冲").then(设);
  useEffect(() => { 刷(); }, []);
  if (!态) return <p className="讯">加载中…</p>;
  return (
    <div>
      <h1 className="题">乱序缓冲</h1>
      <p className="述">
        全局口径：<strong>{态.口径}</strong>。同房事件先入缓冲，释放时按<strong>事件时升序</strong>批量抬水位；
        缓冲释放与水位推进同事务，不会出现「已抬水位但早事件被误旁路」。
        触发释放：{态.策略说明}（超时 {态.缓冲超时秒}s / 批量 {态.缓冲批量}）。
      </p>
      <div className="行">
        <span className={`徽章 ${态.valid ? "通" : "败"}`}>{态.valid ? "无半截" : "半截"}</span>
        <span className="讯" style={{ margin: 0 }}>缓冲深度 {态.缓冲深度}</span>
        <button className="次" onClick={刷}>刷新缓冲</button>
      </div>
      {!态.房间.length ? (
        <div className="空态">无直播间</div>
      ) : (
        态.房间.map((房) => (
          <div className="段" key={房.房间键}>
            <div className="段题">
              {房.房间键} · {房.标题}
              <span className={`徽章 ${房.valid ? "通" : "败"}`} style={{ marginLeft: "0.5rem" }}>
                {房.valid ? "有效" : "无效"}
              </span>
            </div>
            <div className="格">
              <div className="卡"><b>{房.缓冲深度}</b><span>缓冲深度</span></div>
              <div className="卡"><b className="码" style={{ fontSize: "0.9rem" }}>{房.释放水位 || "—"}</b><span>释放水位</span></div>
              <div className="卡"><b className="码" style={{ fontSize: "0.9rem" }}>{房.事件时水位 || "—"}</b><span>当前事件时水位</span></div>
              <div className="卡"><b>{房.旁路集.乙实际.length}</b><span>乙实际旁路</span></div>
              <div className="卡"><b>{房.旁路集.甲反事实.length}</b><span>甲反事实旁路</span></div>
            </div>
            {房.valid问题.length > 0 && (
              <div className="提示条" style={{ borderColor: "var(--败)" }}>{房.valid问题.join("；")}</div>
            )}

            <div className="段题" style={{ marginTop: "0.9rem" }}>旁路集（两口径可区分）</div>
            <div className="提示条">
              乙实际：{房.旁路集.乙实际.length ? 房.旁路集.乙实际.join("、") : "（空）"} ｜
              甲反事实：{房.旁路集.甲反事实.length ? 房.旁路集.甲反事实.join("、") : "（空）"} ｜
              仅甲被误旁路：{房.旁路集.差异.length ? <strong>{房.旁路集.差异.join("、")}</strong> : "无"}
            </div>

            <div className="段题" style={{ marginTop: "0.9rem" }}>缓冲留驻</div>
            {!房.缓冲事件.length ? (
              <div className="空态">缓冲已清空</div>
            ) : (
              <table>
                <thead><tr><th>序</th><th>事件编号</th><th>事件时</th><th>处理时</th><th>入缓水位</th><th>处理时乱序</th></tr></thead>
                <tbody>
                  {房.缓冲事件.map((r) => (
                    <tr key={r.入缓序号}>
                      <td>{r.入缓序号}</td><td>{r.事件编号}</td>
                      <td className="码">{r.事件时}</td><td className="码">{r.处理时}</td>
                      <td className="码">{r.入缓水位}</td>
                      <td>{r.是否处理时乱序 ? <span className="徽章 败">是</span> : "否"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="段题" style={{ marginTop: "0.9rem" }}>释放履历</div>
            {!房.释放履历.length ? (
              <div className="空态">尚无释放</div>
            ) : (
              <table>
                <thead><tr><th>批次</th><th>释放处理时</th><th>水位前</th><th>水位后</th><th>事件数</th><th>排序后事件</th><th>乙旁路</th><th>甲旁路</th></tr></thead>
                <tbody>
                  {房.释放履历.map((h) => (
                    <tr key={h.编号}>
                      <td className="码">{h.释放批次}</td><td className="码">{h.释放处理时}</td>
                      <td className="码">{h.水位前}</td><td className="码">{h.水位后}</td>
                      <td>{h.释放事件数}</td>
                      <td className="码">{h.事件编号集.join(" → ")}</td>
                      <td className="码">{h.乙旁路集.join("、") || "—"}</td>
                      <td className="码">{h.甲旁路集.join("、") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))
      )}
    </div>
  );
}
