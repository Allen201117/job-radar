"""公告抓取主流程：抓官方招聘公告列表 → 抽详情（截止日/发布日/受众）→ upsert + ops 台账。

运行（工作目录 crawler/，.env.local 已 source）：
    python -m announcements.harvest            # 抓全部 portal + 过期治理
    python -m announcements.harvest --dry-run  # 只抓不写库，打印将入库的行（先量用）
    python -m announcements.harvest --portal bj_rsj

⚠️ 归属门在 portals.parse_list 里（只收官方域名 + 可报名公告）；这里不再放宽。
⚠️ 列表缺席 ≠ 撤岗：本流程只 upsert 看到的、touch last_seen_at，从不据「列表里没有」判死。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import httpx

# 兄弟模块走 crawler/ 顶层扁平导入（crawler/ 在 sys.path 上）
import db  # noqa: E402
import ops_runs  # noqa: E402
from adapters.cn_portal_tls import make_transport  # noqa: E402

from .body import extract_body
from .classify import detect_audience, detect_employer_type
from .deadline import extract_published
from .portals import (PORTALS, PORTALS_BY_KEY, Portal, all_list_urls, detail_text,
                      parse_list, _GEO_BLOCKED_FROM_CI)
from .quality import assess

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 单 portal 每轮最多处理的候选数（列表页倒序 = 取最新 N）。
# 防山东那种整档 462 条把详情抓取撑爆；老公告报名多已截止，取最新即可，其余靠下一轮增量补。
# 2026-09-18 从 60 抬到 150：开了翻页（all_list_urls，2~4 页）后单省候选可到 80+，
# 卡在 60 会把翻页翻出来的直接截掉、等于白翻。已入库的 URL 不再抓详情，所以稳态成本只多几个列表页。
_MAX_CANDIDATES_PER_PORTAL = 150


def _client() -> httpx.Client:
    # 复用国内门户 TLS 兼容层（强制 IPv4 + 传统重协商）——本机测不出、CI 上才炸的坑。
    return httpx.Client(
        transport=make_transport(),
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                 "Accept": "text/html,application/xhtml+xml,*/*"},
        timeout=25,
        follow_redirects=True,
    )


def _fetch(client: httpx.Client, url: str, referer: str | None = None) -> str:
    # 有的省 detail 页要 Referer 才给（江苏无 Referer 返 403）；带上无害，统一给 detail 传列表页做 Referer。
    r = client.get(url, headers={"Referer": referer} if referer else None)
    r.raise_for_status()
    return r.content.decode(r.encoding or "utf-8", errors="replace")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def harvest_portal(client: httpx.Client, sb, portal: Portal, dry_run: bool) -> dict:
    """抓一个 portal，返回台账指标 dict。"""
    # 1. 列表页 → 候选（已过归属门 + 内容过滤）
    candidates = []
    seen: set[str] = set()
    list_errors = 0
    list_urls = all_list_urls(portal)
    for idx, lu in enumerate(list_urls):
        # 抓取 + 解析都算「列表页」这一步：解析抛错（如 script_json 形态变了）计 list_errors，别崩整轮。
        try:
            html = _fetch(client, lu)
            items = parse_list(portal, lu, html)
        except Exception as exc:  # noqa: BLE001
            # ⚠️ 翻页页面 404 = 「没有更多页了」，不是故障：某省公告变少时页数自然缩水
            # （陕西那个栏目就只有 2 页）。把它记成 list_errors 会让 CI 天天报假错，
            # 而真正该报警的是**第一页**打不开 —— 那才说明栏目没了或被拦。
            is_missing_page = idx > 0 and isinstance(exc, httpx.HTTPStatusError) \
                and exc.response.status_code in (404, 410)
            if not is_missing_page:
                list_errors += 1
                sys.stderr.write(f"[announce] {portal.key} 列表页失败 {lu}: {type(exc).__name__}\n")
            continue
        for item in items:
            if item.url in seen:
                continue
            seen.add(item.url)
            candidates.append(item)

    # 列表页倒序 → 截最新 N，防整档（如山东 462 条）把详情抓取撑爆。
    total_found = len(candidates)
    candidates = candidates[:_MAX_CANDIDATES_PER_PORTAL]

    # 2. 已在库的 source_url（用于区分新增/更新；dry-run 不读库，全部当新的抽一遍）
    existing: dict[str, dict] = {}
    if not dry_run:
        rows = db.fetch_all_rows(
            lambda: sb.table("announcement_postings")
            .select("id, source_url, deadline")
            .eq("source_portal", portal.key),
            order_key="id",
        )
        existing = {r["source_url"]: r for r in rows}

    new_rows, touched, deadline_hit, detail_errors = [], 0, 0, 0
    rejected, rejected_reasons = 0, {}
    for item in candidates:
        if item.url in existing:
            if not dry_run:
                sb.table("announcement_postings").update(
                    {"last_seen_at": _now_iso(), "updated_at": _now_iso()}
                ).eq("source_url", item.url).execute()
            touched += 1
            continue
        # 新公告 → 抽详情（带列表页做 Referer，绕过江苏那类 detail 反爬）
        try:
            dhtml = _fetch(client, item.url, referer=portal.list_urls[0])
        except Exception as exc:  # noqa: BLE001
            detail_errors += 1
            sys.stderr.write(f"[announce] {portal.key} 详情失败 {item.url}: {type(exc).__name__}\n")
            continue
        # ⚠️ 判断一律落在**正文**上，不用整页文本：整页含导航/侧栏/友情链接/页脚，
        #   既会让「正文里有没有 X」被导航词命中，也可能把侧栏别条公告的日期当成本公告的截止日。
        dtext = extract_body(detail_text(portal, dhtml), item.title)
        published = item.published_at or extract_published(dtext)
        v = assess(item.title, dtext, published_at=published)
        if not v.ok and v.action == "reject":
            # 标题带「招聘」但点进去是过程通知 / 报名已关门 / 已过截止日 → 压根别入库。
            # 这些此前会入库并一直展示到 45 天 TTL，正是「点进去是招聘结束的公示」的来源。
            rejected += 1
            rejected_reasons[v.reason] = rejected_reasons.get(v.reason, 0) + 1
            continue
        deadline, deadline_text = v.deadline, v.deadline_text
        if deadline:
            deadline_hit += 1
        new_rows.append({
            "source_portal": portal.key,
            "source_url": item.url,
            "title": item.title,
            "region": portal.region,
            "employer_type": detect_employer_type(item.title),
            "audience": detect_audience(item.title + " " + dtext[:2000]),
            "published_at": published.isoformat() if published else None,
            "deadline": deadline.isoformat() if deadline else None,
            "deadline_text": deadline_text,
            "status": "active",
            "verdict": "index_page" if v.action == "flag" else "ok",
            "last_seen_at": _now_iso(),
            "updated_at": _now_iso(),
        })

    if new_rows and not dry_run:
        sb.table("announcement_postings").upsert(new_rows, on_conflict="source_url").execute()

    metrics = {
        "portal": portal.key,
        "found": total_found,            # 列表页命中的候选总数（截断前）
        "processed": len(candidates),    # 本轮实际处理（截最新 N）
        "new": len(new_rows),
        "rejected": rejected,              # 过了标题门、但正文判「现在报不了」被拦下的
        "rejected_reasons": rejected_reasons,
        "touched": touched,
        "deadline_hit": deadline_hit,
        "list_errors": list_errors,
        "detail_errors": detail_errors,
    }
    if dry_run:
        metrics["dry_run_rows"] = new_rows
    return metrics


def run(portal_keys: list[str] | None, dry_run: bool, include_geo_blocked: bool = False) -> dict:
    if portal_keys:
        portals = [PORTALS_BY_KEY[k] for k in portal_keys]
    elif include_geo_blocked:
        # 只有大陆 runner（如创始人 Mac 的 launchd）才带这个 —— 它连得上 GitHub US runner 挡掉的省。
        portals = [*PORTALS, *_GEO_BLOCKED_FROM_CI]
    else:
        portals = list(PORTALS)
    sb = None if dry_run else db.get_supabase()
    started = _now_iso()
    per_portal = []
    with _client() as client:
        for p in portals:
            m = harvest_portal(client, sb, p, dry_run)
            per_portal.append(m)
            print(f"[announce] {p.key}: 候选 {m['found']} / 新增 {m['new']} / 正文拦下 {m['rejected']} / 更新 {m['touched']} "
                  f"/ 抽到截止日 {m['deadline_hit']} / 列表错 {m['list_errors']} / 详情错 {m['detail_errors']}")

    total_new = sum(m["new"] for m in per_portal)
    total_found = sum(m["found"] for m in per_portal)
    total_err = sum(m["list_errors"] + m["detail_errors"] for m in per_portal)
    # HTTP 200 + 空候选同样是假阴性：逐 portal 叫出来，别让其他省的产出把它盖绿。
    zero_found_portals = [m["portal"] for m in per_portal
                          if m["found"] == 0 and m["list_errors"] == 0]
    for key in zero_found_portals:
        print(f"::warning::[announce] {key} found 0 candidates（形态可能变了）")
    # 零产出出声：候选为 0 或全是错，别静默绿灯（工程化底线）。
    status = ops_runs.status_from_counts(processed=total_found, failed=total_err)
    if total_found == 0:
        status = "failed"
        print("::warning::[announce] 全部 portal 候选为 0 —— 疑似列表页形态变了或被拦")

    metrics = {
        "portals": [{k: v for k, v in m.items() if k != "dry_run_rows"} for m in per_portal],
        # Mac 的 --include-geo-blocked 是 27 省主 runner；默认分支是 CI 的可达省兜底。
        "runner": "mac" if include_geo_blocked else "ci",
        "portals_run": len(portals),
        "total_found": total_found,
        "total_new": total_new,
        "total_rejected": sum(m["rejected"] for m in per_portal),
        "total_deadline_hit": sum(m["deadline_hit"] for m in per_portal),
        "total_errors": total_err,
        "zero_found_portals": zero_found_portals,
    }
    if not dry_run and sb is not None:
        ops_runs.record_ops_run(sb, "announcement_harvest", metrics,
                                status=status, started_at=started, finished_at=_now_iso())
    return {"per_portal": per_portal, "metrics": metrics}


def main() -> int:
    ap = argparse.ArgumentParser(description="公告抓取")
    ap.add_argument("--dry-run", action="store_true", help="只抓不写库，打印将入库的行")
    ap.add_argument("--portal", action="append", help="只跑指定 portal key，可多次")
    ap.add_argument("--include-geo-blocked", action="store_true",
                    help="额外跑 _GEO_BLOCKED_FROM_CI 那几个省（只有大陆 runner 连得上，如创始人 Mac 的 launchd）")
    ap.add_argument("--no-expire", action="store_true", help="跳过过期治理")
    args = ap.parse_args()

    db.load_environment()
    result = run(args.portal, args.dry_run, include_geo_blocked=args.include_geo_blocked)

    if args.dry_run:
        for m in result["per_portal"]:
            for row in m.get("dry_run_rows", []):
                print(f"  · [{row['audience']}] {row['title'][:40]} | 截止 {row['deadline'] or row['deadline_text'] or '—'} "
                      f"| 发布 {row['published_at'] or '—'}")
    elif not args.no_expire:
        from .expire import expire
        sb = db.get_supabase()
        exp = expire(sb)
        print(f"[announce] 过期治理：截止日过期 {exp['by_deadline']} / TTL 兜底 {exp['by_ttl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
