"""crawler/harvest_beisen_routes.py — 一次性/周期性持久化 beisen 各租户详情路由到 beisen_routes.json。

为何：beisen 列表已能纯 httpx 抓（adapters/china_ats.BeisenAdapter._httpx_fetch），但 jd_url 需本租户详情
路由（点击捕获，浏览器探测），只有 route 已缓存的租户才能走 httpx。本脚本浏览器逐家探出路由并落盘——
覆盖到（近）全部 enabled beisen 租户后，beisen 即可进 daily-crawl httpx 快车道（4×/天 + list-absence）。

慢（浏览器逐家），故每次 cap 一批、**逐家增量落盘**（中途崩也不丢已探到的），由 workflow 每晚跑 + commit 回仓，
几晚覆盖全部。已缓存 route 的租户跳过；探不到的留待下次重试（不落 None，避免永久跳过可能恢复的租户）。
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import db

sys.path.insert(0, os.path.dirname(__file__))
from adapters import china_ats  # noqa: E402

CAP = int(os.environ.get("HARVEST_BEISEN_CAP", "40"))   # 每次最多探多少家未缓存租户（浏览器慢）
_ROUTES_FILE = Path(china_ats._BEISEN_ROUTES_FILE)


def _usable(route):
    """只持久化可拼 jd_url 的路由（str=detail base / dict 含 template）；None/空不落盘（留待重试）。"""
    if isinstance(route, str) and route.strip():
        return route
    if isinstance(route, dict) and route.get("template"):
        return route
    return None


def main():
    sb = db.get_supabase()
    rows = (sb.table("sources").select("source_url")
            .eq("enabled", True).eq("adapter_name", "beisen").execute().data) or []
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
            ad.fetch(url)  # route 未缓存 → 走浏览器探+缓存到 _BEISEN_ROUTE_CACHE[host]
            route = _usable(china_ats._BEISEN_ROUTE_CACHE.get(host))
        except Exception as e:
            route = None
            print(f"  ✗ {host}: {type(e).__name__}: {str(e)[:50]}", flush=True)
        if route:
            routes[host] = route
            harvested += 1
            print(f"  ✓ {host} → {route if isinstance(route, str) else route.get('template')}", flush=True)
            # 逐家增量落盘（中途崩不丢）
            try:
                _ROUTES_FILE.write_text(json.dumps(routes, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"    落盘失败: {e}", flush=True)

    print(f"[harvest-beisen] 本次新探到 {harvested} 家；beisen_routes.json 现共 {len(routes)} 家。", flush=True)


if __name__ == "__main__":
    main()
