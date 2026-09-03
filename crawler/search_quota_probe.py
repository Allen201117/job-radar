#!/usr/bin/env python3
"""搜索额度余量探针：把「还剩多少」变成能主动叫的数字。

为什么要有它（2026-09-04 立）：
  Serper 的免费额度是 **2,500 次一次性总额**，用完就没了，而且是**静默**的——
  表现会是「T3 突然不产出」，又一次「绿灯零产出」（本仓库反复栽在这类故障上）。
  在此之前，「快用完了」完全靠人事后翻台账推算，没有任何告警。

两个口径，分清楚：
  · **台账口径**（本文件的主力）：我们自己每次检索记的账（search_usage / qianfan_usage）。
    一定拿得到，不需要各家的 key，缺点是只能从台账建立那天算起。
  · **官方口径**：各家余额 API。拿得到就用它覆盖台账估算（更权威），
    拿不到就如实标注 `source=ledger`，**绝不把估算说成实测**。

退出码：正常 0；任一「一次性额度」越过 90% 时退出 1 —— 让 CI 标红、GitHub 发邮件，
这是它「会主动叫」的出口，不然又是一个没人看的日志。
"""
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import datetime, timezone

import db
import ops_runs

# 各家免费额度口径。kind 决定「用了多少」该怎么算：
#   lifetime = 一次性总额，累计算；monthly = 按自然月重置；daily = 按天重置
# ⚠️ bocha 是**付费**不是免费额度，不参与耗尽预警（配了就是花钱，不存在「用完」）。
QUOTA_SPEC = {
    "tavily": {"kind": "monthly", "free": 1000, "note": "1,000/月，自然月重置"},
    "serper": {"kind": "lifetime", "free": 2500, "note": "2,500 一次性总额，用完即止"},
    # 官方口径是「每月 1,500 次**按天发放**」，50/天是 1500÷30 除出来的近似；
    # 我们的硬顶就按 50/天 执行（crawler 侧自封顶 40，留 10 给 /api/discovery 交互）。
    "qianfan": {"kind": "daily", "free": 50, "note": "官方 1,500/月按天发放（≈50/天）"},
    "bocha": {"kind": "paid", "free": None, "note": "付费，不是免费额度"},
}

WARN_RATIO = 0.8
CRITICAL_RATIO = 0.9


# ── 官方口径探测：只有真实存在的接口才写在这里 ──────────────────────────
# 2026-09-04 查过三家文档：
#   · Tavily  ✅ GET https://api.tavily.com/usage（Authorization: Bearer <key>）
#   · Serper  ❌ 无余额 API，响应头也不带剩余额度 → 只能靠台账
#   · 千帆    ❌ AI 搜索没有余额查询接口（平台上那个 freeQuota 是向量数据库的，别搞混）
# 所以「官方口径」目前只有 Tavily 一家；其余如实标 source=ledger，
# **绝不把台账估算说成实测**。
TAVILY_USAGE_URL = "https://api.tavily.com/usage"


def probe_tavily(api_key: str, timeout: float = 15.0) -> dict | None:
    """查 Tavily 官方用量。拿不到返回 None（探针不该因为一家挂了就整体失败）。

    返回 {"used": int, "limit": int}。字段口径见 docs.tavily.com 的 /usage：
    key.usage / key.limit 是本 key 当前计费周期的用量与上限。
    """
    if not api_key:
        return None
    try:
        import httpx
        resp = httpx.get(TAVILY_USAGE_URL,
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as exc:
        print(f"[quota] Tavily 官方用量查询失败，回退台账：{type(exc).__name__}: {str(exc)[:100]}")
        return None
    return parse_tavily_usage(data)


def parse_tavily_usage(data) -> dict | None:
    """纯函数：Tavily /usage 响应 → {"used","limit"}；形状不认识就返回 None，不猜。"""
    if not isinstance(data, dict):
        return None
    for container in (data.get("key"), data.get("account"), data):
        if not isinstance(container, dict):
            continue
        used = container.get("usage", container.get("plan_usage"))
        limit = container.get("limit", container.get("plan_limit"))
        if isinstance(used, (int, float)) and isinstance(limit, (int, float)) and limit > 0:
            return {"used": int(used), "limit": int(limit)}
    return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _this_month() -> str:
    return _today()[:7]


def ledger_rows(sb) -> list:
    """search_usage + qianfan_usage 统一成 [{provider, day, used}]。

    千帆走的是**另一张表**（qianfan_usage，早于多源路由就存在），
    只看 search_usage 会以为千帆从没用过——这正是今天差点误判的点。
    """
    rows = [
        {"provider": r.get("provider"), "day": str(r.get("day") or "")[:10],
         "used": int(r.get("used") or 0)}
        for r in db.fetch_all_rows(
            lambda: sb.table("search_usage").select("provider,day,used"), order_key="day")
    ]
    try:
        rows += [
            {"provider": "qianfan", "day": str(r.get("day") or "")[:10],
             "used": int(r.get("used") or 0)}
            for r in db.fetch_all_rows(
                lambda: sb.table("qianfan_usage").select("day,used"), order_key="day")
        ]
    except Exception as exc:  # 千帆表读不到不该让整个探针失败
        print(f"[quota] qianfan_usage 读取失败，本次不含千帆：{type(exc).__name__}")
    return rows


def summarize(rows: list, today: str | None = None, month: str | None = None) -> dict:
    """纯函数：台账行 → 每个源的 {lifetime, month, today, first_day, days}。"""
    today = today or _today()
    month = month or today[:7]
    acc: dict = defaultdict(lambda: {"lifetime": 0, "month": 0, "today": 0,
                                     "first_day": None, "days": 0})
    seen_days: dict = defaultdict(set)
    for row in rows or []:
        provider, day, used = row.get("provider"), row.get("day"), int(row.get("used") or 0)
        if not provider or not day:
            continue
        item = acc[provider]
        item["lifetime"] += used
        if day[:7] == month:
            item["month"] += used
        if day == today:
            item["today"] += used
        if item["first_day"] is None or day < item["first_day"]:
            item["first_day"] = day
        seen_days[provider].add(day)
    for provider, item in acc.items():
        item["days"] = len(seen_days[provider])
    return dict(acc)


def assess(summary: dict, spec: dict | None = None) -> list:
    """纯函数：用量 → [{provider, kind, used, quota, pct, level, note}]，按紧迫度排序。

    level：ok / warn(≥80%) / critical(≥90%)。付费源与没有额度口径的源一律 ok（不预警）。
    """
    spec = spec if spec is not None else QUOTA_SPEC
    out = []
    for provider, meta in spec.items():
        item = summary.get(provider) or {"lifetime": 0, "month": 0, "today": 0, "days": 0}
        kind = meta["kind"]
        quota = meta["free"]
        used = {"lifetime": item["lifetime"], "monthly": item["month"],
                "daily": item["today"]}.get(kind)
        if kind == "paid" or not quota or used is None:
            out.append({"provider": provider, "kind": kind, "used": item["lifetime"],
                        "quota": None, "pct": None, "level": "ok", "note": meta["note"]})
            continue
        # ⚠️ 判定用**原始比值**，不用四舍五入后的百分比：
        # 1999/2500 = 79.96%，round(…,1) 会变成 80.0 从而误报 warn。
        # pct 只用于显示，圆整不该改变结论。
        ratio = used / quota
        pct = round(ratio * 100, 1)
        level = "critical" if ratio >= CRITICAL_RATIO else (
            "warn" if ratio >= WARN_RATIO else "ok")
        out.append({"provider": provider, "kind": kind, "used": used, "quota": quota,
                    "pct": pct, "level": level, "note": meta["note"]})
    order = {"critical": 0, "warn": 1, "ok": 2}
    return sorted(out, key=lambda x: (order[x["level"]], -(x["pct"] or 0)))


def days_left(item: dict, summary: dict) -> float | None:
    """一次性额度还能撑几天：按该源「有记录天数」的平均日耗算。算不出返回 None。"""
    if item["kind"] != "lifetime" or not item.get("quota"):
        return None
    stat = summary.get(item["provider"]) or {}
    days = stat.get("days") or 0
    if days <= 0 or stat.get("lifetime", 0) <= 0:
        return None
    per_day = stat["lifetime"] / days
    return round(max(0, item["quota"] - item["used"]) / per_day, 1) if per_day else None


def main():
    parser = argparse.ArgumentParser(description="搜索额度余量探针（台账口径）")
    parser.add_argument("--no-fail", action="store_true",
                        help="即使有源越过 90% 也返回 0（本地查看用）")
    args = parser.parse_args()

    sb = db.get_supabase()
    rows = ledger_rows(sb)
    summary = summarize(rows)

    # 官方口径优先：拿得到就用它覆盖台账估算，并记下 source，报告里如实标注。
    sources = {name: "ledger" for name in QUOTA_SPEC}
    live_tavily = probe_tavily(os.environ.get("TAVILY_API_KEY", ""))
    spec = {k: dict(v) for k, v in QUOTA_SPEC.items()}
    if live_tavily:
        summary.setdefault("tavily", {"lifetime": 0, "month": 0, "today": 0, "days": 0})
        summary["tavily"]["month"] = live_tavily["used"]
        spec["tavily"]["free"] = live_tavily["limit"]
        sources["tavily"] = "api"

    report = assess(summary, spec)

    print("搜索额度余量（台账口径；各家余额 API 的 key 只在 CI，本地拿不到）")
    print(f"{'源':10s} {'口径':8s} {'已用':>8s} {'额度':>8s} {'占比':>7s}  状态  说明")
    critical = []
    for item in report:
        quota = "—" if item["quota"] is None else str(item["quota"])
        pct = "—" if item["pct"] is None else f"{item['pct']}%"
        mark = {"ok": "  ", "warn": "⚠ ", "critical": "✗ "}[item["level"]]
        # 台账估算 vs 官方实测，必须一眼分得出，别让人把估算当实测用
        extra = ("[官方]" if sources.get(item["provider"]) == "api" else "[台账]") + item["note"]
        left = days_left(item, summary)
        if left is not None:
            extra += f"；按当前速度约还能撑 {left} 天"
        print(f"{item['provider']:10s} {item['kind']:8s} {item['used']:>8d} {quota:>8s} "
              f"{pct:>7s}  {mark}{extra}")
        if item["level"] == "critical":
            critical.append(item)

    metrics = {"tavily_source": sources.get("tavily", "ledger"),
               "providers": len(report),
               "critical": len(critical),
               "warn": sum(1 for i in report if i["level"] == "warn")}
    for item in report:
        metrics[f"{item['provider']}_used"] = item["used"]
        if item["pct"] is not None:
            metrics[f"{item['provider']}_pct"] = item["pct"]
    try:
        ops_runs.record_ops_run(sb, "search_quota_probe", metrics,
                                status="failure" if critical else "success")
    except Exception as exc:  # 台账写失败不该盖住探针本身的结论
        print(f"[quota] ops_runs 写入失败：{type(exc).__name__}")

    if critical and not args.no_fail:
        names = "、".join(i["provider"] for i in critical)
        print(f"\n✗ {names} 的额度已越过 90% —— 用完是静默的，会表现为「洞察突然不产出」。")
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
