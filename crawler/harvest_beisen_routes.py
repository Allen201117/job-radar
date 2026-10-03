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


# 人工定论「这行永久停用、勿再探」的漏斗行（迁移 201 写的就是这个前缀）。
_CLOSED_NOTE_PREFIX = "gap_funnel:closed"


def _is_harvest_candidate(row):
    """这一行源要不要进待探队列。

    enabled 一律要；disabled 只要「漏斗待验收」的（notes 前缀 gap_funnel:）——理由见 _run 开头注释。
    但 gap_funnel:closed 是人工定论「此行永久停用，勿再探」，**不是待验收**：
    ❌ 2026-09-23~27 建发集团（chinacdc.zhiye.com）每晚探失败：「SSR 列表页无 jobId/adId 锚点」或 goto 超时。
    该租户两条源：enabled 的 /subzw/ 是老版 CMS、零浏览器可抓（迁移 199 live 110 岗，daily 一直在抓出岗），
    停用的 /campus 是 gap_funnel:closed（迁移 201 实测「200 但 0 岗，站点空壳」）。CMS 分支对 /subzw/ 能出岗
    就会登记 {"cms": true} 而不会走到那条报错，报错签名只对得上空壳 /campus——旧实现按 id 序取同 host 第一条，
    探的是它（旧日志只打 host 不打 URL，所以此前没人看出来；现在 ✗ 行带 URL）。
    """
    if row.get("enabled"):
        return True
    notes = str(row.get("notes") or "")
    return notes.startswith("gap_funnel:") and not notes.startswith(_CLOSED_NOTE_PREFIX)


def _pending_hosts(rows, cached):
    """待探队列：[(host, source_url)]，同 host 只探一条。

    ⚠️ 同 host 有多条源时**优先 enabled 那条的 URL**：路由按 host 缓存，但探测是拿某一条 source_url 去 fetch 的，
    挑中一条空板块（停用的 /campus）就等于替整个租户下了「探不出」的结论。原实现按 id 序取第一条，
    谁先谁后全凭 uuid 的字面大小。
    """
    candidates = [r for r in rows if _is_harvest_candidate(r)]
    candidates.sort(key=lambda r: not r.get("enabled"))   # 稳定排序：enabled 在前，同组内保持原顺序
    seen, uniq = set(), []
    for r in candidates:
        url = r.get("source_url") or ""
        host = urlparse(url).netloc
        if not host or host in cached or host in seen:
            continue
        seen.add(host)
        uniq.append((host, url))
    return uniq


def _browser_only_payload(payload):
    """fetch() 的返回是不是「浏览器渲染列表页、jd_url 直接取自页面锚点」的产物。

    这类租户（老版 SSR 门户但列表是 JS 渲染，如华安基金 huaan.zhiye.com，见 test_beisen_ssr_paged
    的 test_non_jobstable_page_yields_nothing）fetch() 能抓出带 jd_url 的岗，却**没有任何零浏览器路由可存**：
    httpx 的 cms / ssr / cards 三个分支都读不到列表（成功时它们会自己登记标记），只有浏览器 _fetch_ssr 读得到。
    所以对 harvest 来说它不是「探失败」，而是「这家本来就只能走浏览器档，没东西可存」。
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else None
    except ValueError:
        return False
    if not isinstance(data, dict):
        return False
    jobs = data.get("_ssr_jobs")
    return isinstance(jobs, list) and any(isinstance(j, dict) and j.get("jd_url") for j in jobs)


def _run(sb, started_at):
    # 分页拉全量：本过滤当前 331 行未触顶 PostgREST 的 1000 行硬顶，但 beisen 源随每日扩源持续涨 → 走统一 helper。
    # ⚠️ 不能只取 enabled：缺口漏斗按验收门规矩「先插 disabled 源 → 真抓 → 回读健康岗才 enable」，
    # 而北森新租户不先 harvest 到详情路由就抓不出岗 → 只探 enabled 会形成死结
    # （disabled 永远拿不到路由 → 永远抓不出岗 → 永远 enable 不了 → 永远不被 harvest）。
    # 所以把「漏斗待验收」的 disabled 源也纳进来（notes 前缀 gap_funnel:，closed 除外，见 _is_harvest_candidate）。
    rows = db.fetch_all_rows(
        lambda: sb.table("sources").select("source_url,enabled,notes")
        .eq("adapter_name", "beisen"))
    # 现有落盘 route（china_ats 启动已载入 _BEISEN_ROUTE_CACHE）
    routes = dict(china_ats._BEISEN_ROUTE_CACHE)
    uniq = _pending_hosts(rows, routes)
    n_rows = sum(1 for r in rows if _is_harvest_candidate(r))
    print(f"[harvest-beisen] enabled={n_rows} 已缓存={len(routes)} 待探={len(uniq)} → 本次探前 {CAP} 家", flush=True)

    harvested = 0
    browser_only, failed_hosts = [], []
    for host, url in uniq[:CAP]:
        payload, crashed = None, False
        try:
            ad = china_ats.BeisenAdapter()
            payload = ad.fetch(url)  # route 未缓存 → 探测并缓存到 _BEISEN_ROUTE_CACHE[host]
            # （多数走浏览器点击捕获；老版 CMS/卡片式/SSR 租户零浏览器可抓，登记的是
            #  {"cms"/"cards"/"ssr": true}）
            route = _usable(china_ats._BEISEN_ROUTE_CACHE.get(host))
        except Exception as e:
            route, crashed = None, True
            failed_hosts.append(host)
            print(f"  ✗ {host}: {type(e).__name__}: {str(e)[:50]}  ({url})", flush=True)
        if route:
            routes[host] = route
            harvested += 1
            print(f"  ✓ {host} → {_describe(route)}", flush=True)
            # 逐家增量落盘（中途崩不丢）
            try:
                # 不用 Path.write_text(newline=)：该参数 3.10 才有，本地 3.9 会 TypeError 被下面的 except 吞掉、路由一条都存不下来。
                with open(_ROUTES_FILE, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(json.dumps(routes, ensure_ascii=False, indent=2))
            except Exception as e:
                print(f"    落盘失败: {e}", flush=True)
        elif crashed:
            pass
        elif _browser_only_payload(payload):
            # 2026-09-25~27 华安基金（huaan.zhiye.com，d99d391 实测「列表是 JS 渲染」）每晚都是「不抛错、
            # 也没登记路由」：日志里一行都没有，台账却把它记成探失败——规则 A 连续零产出的另一半。
            # 旧日志分不出它落在本分支还是下面的 else，新日志逐家打出来。
            browser_only.append(host)
            print(f"  · {host}: 只能浏览器抓（列表 JS 渲染，jd_url 取自页面锚点），无零浏览器路由可存", flush=True)
        else:
            failed_hosts.append(host)
            print(f"  ✗ {host}: 抓到列表但没探出可用详情路由  ({url})", flush=True)

    probed = len(uniq[:CAP])
    # attempted = 「还有零浏览器路由可探」的租户数（2026-09-28 起不含 browser_only）。
    # 规则 A 按 attempted 判「有活干」：只剩只能走浏览器的租户时 = 0 = 空队列，不是零产出。
    # 刻意沿用 attempted 这个键而不是新起一个：改前的台账行照旧按原值判（那几天建发是真探失败，判 zero 没错），
    # 不会因为换了口径被倒回去改判成 idle。
    attempted = probed - len(browser_only)
    print(f"[harvest-beisen] 本次新探到 {harvested} 家；只能浏览器 {len(browser_only)} 家；"
          f"探失败 {len(failed_hosts)} 家；beisen_routes.json 现共 {len(routes)} 家。", flush=True)

    ops_runs.record_ops_run(
        sb, "harvest_beisen_routes",
        {"harvested": harvested, "attempted": attempted, "probed": probed,
         "browser_only": len(browser_only), "failed": len(failed_hosts),
         "cached_total": len(routes), "pending": len(uniq)},
        ops_runs.status_from_counts(attempted, len(failed_hosts)),
        started_at=started_at,
    )


if __name__ == "__main__":
    main()
