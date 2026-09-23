"""crawler/harvest_beisen_routes.py — 一次性/周期性持久化 beisen 各租户详情路由到 beisen_routes.json。

为何：beisen 列表已能纯 httpx 抓（adapters/china_ats.BeisenAdapter._httpx_fetch），但 jd_url 需本租户详情
路由，只有 route 已缓存的租户才能走 httpx 快车道。多数租户需要浏览器点击捕获才能探出 template 路由；
但老版 CMS / 卡片式 / SSR「jobsTable」这三类门户零浏览器可抓（jd_url 来自列表锚点本身），本脚本调用一次
`ad.fetch(url)` 就够——命中哪一类，china_ats.fetch() 会自己把 {"cms"/"cards"/"ssr": true} 写进
_BEISEN_ROUTE_CACHE，本脚本只管读缓存、落盘（2026-09-23 前这三类的登记漏了，详情见 _usable() 的注释）。
覆盖到（近）全部 enabled beisen 租户后，beisen 即可进 daily-crawl httpx 快车道（4×/天 + list-absence）。

慢（真正需要浏览器点击捕获的租户），故每次 cap 一批、**逐家增量落盘**（中途崩也不丢已探到的），由
workflow 每晚跑 + commit 回仓，几晚覆盖全部。已缓存 route 的租户跳过；探不到的留待下次重试（不落
None，避免永久跳过可能恢复的租户）。
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import db
import ops_runs

sys.path.insert(0, os.path.dirname(__file__))
from adapters import china_ats  # noqa: E402

CAP = int(os.environ.get("HARVEST_BEISEN_CAP", "40"))   # 每次最多探多少家未缓存租户（浏览器慢）
_ROUTES_FILE = Path(china_ats._BEISEN_ROUTES_FILE)


def _usable(route):
    """只持久化「能拼 jd_url 或已确认零浏览器可抓」的路由：str/dict 含 template（点击捕获），
    或 {"cms": true}/{"cards": true}/{"ssr": true}（老版 CMS / 卡片式 / SSR「jobsTable」门户，
    jd_url 来自列表锚点本身，不需要 template）。None/其它形状不落盘（留待重试）。

    ⚠️ 判据必须复用 china_ats._beisen_route_usable，不能在这里另起一套「能用」的定义——
    2026-09-23 实测：这里原来只认 template，导致 fetch() 已经证明可用的 {"cms": true}/
    {"ssr": true} 标记被判成「不可用」，26 个待探租户里 25 个（2 cms + 23 ssr）天天被当成
    「还没探出路由」重探，harvested 连续 3 天为 0（它们其实早就能纯 httpx 抓全，压根不需要
    探测；剩下 1 个才是真需要浏览器点击捕获的）。两处判据一旦漂移，症状会一模一样地复发。
    """
    if isinstance(route, str) and route.strip():
        return route
    if isinstance(route, dict) and china_ats._beisen_route_usable(route):
        return route
    return None


def _describe(route):
    """给日志用的可读摘要：template 路由打印模板本身，cms/cards/ssr 标记打印类型名。"""
    if isinstance(route, str):
        return route
    if route.get("template"):
        return route.get("template")
    if route.get("cms"):
        return "cms"
    if route.get("cards"):
        return "cards"
    if route.get("ssr"):
        return "ssr"
    return route


def main():
    started_at = datetime.now(timezone.utc)
    try:
        sb = db.get_supabase()
    except Exception as e:
        sys.stderr.write(f"[harvest-beisen] 无法获取 Supabase client，台账写不了: {type(e).__name__}\n")
        raise
    try:
        return _run(sb, started_at)
    except Exception as e:
        # 中途任何未捕获异常都要留痕（取源列表失败等），再原样抛出保持原退出码。
        ops_runs.record_ops_run(
            sb, "harvest_beisen_routes", {"crash": type(e).__name__}, "failed", started_at=started_at,
        )
        raise


def _run(sb, started_at):
    # 分页拉全量：本过滤当前 331 行未触顶 PostgREST 的 1000 行硬顶，但 beisen 源随每日扩源持续涨 → 走统一 helper。
    # ⚠️ 不能只取 enabled：缺口漏斗按验收门规矩「先插 disabled 源 → 真抓 → 回读健康岗才 enable」，
    # 而北森新租户不先 harvest 到详情路由就抓不出岗 → 只探 enabled 会形成死结
    # （disabled 永远拿不到路由 → 永远抓不出岗 → 永远 enable 不了 → 永远不被 harvest）。
    # 所以把「漏斗待验收」的 disabled 源也纳进来（notes 前缀 gap_funnel:）。
    rows = db.fetch_all_rows(
        lambda: sb.table("sources").select("source_url,enabled,notes")
        .eq("adapter_name", "beisen"))
    rows = [r for r in rows
            if r.get("enabled") or str(r.get("notes") or "").startswith("gap_funnel:")]
    # 现有落盘 route（china_ats 启动已载入 _BEISEN_ROUTE_CACHE）
    routes = dict(china_ats._BEISEN_ROUTE_CACHE)
    todo = []
    for r in rows:
        host = urlparse(r["source_url"]).netloc
        if host and host not in routes:
            todo.append((host, r["source_url"]))
    # 同 host 去重，保第一条 source_url
    seen, uniq = set(), []
    for host, url in todo:
        if host not in seen:
            seen.add(host)
            uniq.append((host, url))
    print(f"[harvest-beisen] enabled={len(rows)} 已缓存={len(routes)} 待探={len(uniq)} → 本次探前 {CAP} 家", flush=True)

    harvested = 0
    for host, url in uniq[:CAP]:
        try:
            ad = china_ats.BeisenAdapter()
            ad.fetch(url)  # route 未缓存 → 探测并缓存到 _BEISEN_ROUTE_CACHE[host]
            # （多数走浏览器点击捕获；老版 CMS/卡片式/SSR 租户零浏览器可抓，登记的是
            #  {"cms"/"cards"/"ssr": true}）
            route = _usable(china_ats._BEISEN_ROUTE_CACHE.get(host))
        except Exception as e:
            route = None
            print(f"  ✗ {host}: {type(e).__name__}: {str(e)[:50]}", flush=True)
        if route:
            routes[host] = route
            harvested += 1
            print(f"  ✓ {host} → {_describe(route)}", flush=True)
            # 逐家增量落盘（中途崩不丢）
            try:
                _ROUTES_FILE.write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"    落盘失败: {e}", flush=True)

    attempted = len(uniq[:CAP])
    print(f"[harvest-beisen] 本次新探到 {harvested} 家；beisen_routes.json 现共 {len(routes)} 家。", flush=True)

    ops_runs.record_ops_run(
        sb, "harvest_beisen_routes",
        {"harvested": harvested, "attempted": attempted, "cached_total": len(routes), "pending": len(uniq)},
        ops_runs.status_from_counts(attempted, attempted - harvested),
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
