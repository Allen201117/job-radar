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
from selectolax.parser import HTMLParser

# 兄弟模块走 crawler/ 顶层扁平导入（crawler/ 在 sys.path 上）
import db  # noqa: E402
import ops_runs  # noqa: E402
from adapters.cn_portal_tls import make_transport  # noqa: E402

from .classify import detect_audience, detect_employer_type
from .deadline import extract_deadline, extract_published
from .portals import PORTALS, PORTALS_BY_KEY, Portal, parse_list

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 单 portal 每轮最多处理的候选数（列表页倒序 = 取最新 N）。
# 防山东那种整档 462 条把详情抓取撑爆；老公告报名多已截止，取最新即可，其余靠下一轮增量补。
_MAX_CANDIDATES_PER_PORTAL = 60


def _client() -> httpx.Client:
    # 复用国内门户 TLS 兼容层（强制 IPv4 + 传统重协商）——本机测不出、CI 上才炸的坑。
    return httpx.Client(
        transport=make_transport(),
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                 "Accept": "text/html,application/xhtml+xml,*/*"},
        timeout=25,
        follow_redirects=True,
    )


def _fetch(client: httpx.Client, url: str) -> str:
    r = client.get(url)
    r.raise_for_status()
    return r.content.decode(r.encoding or "utf-8", errors="replace")


def _visible_text(html: str) -> str:
    tree = HTMLParser(html)
    for node in tree.css("script, style"):
        node.decompose()
    body = tree.body or tree
    return body.text(separator=" ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def harvest_portal(client: httpx.Client, sb, portal: Portal, dry_run: bool) -> dict:
    """抓一个 portal，返回台账指标 dict。"""
    # 1. 列表页 → 候选（已过归属门 + 内容过滤）
    candidates = []
    seen: set[str] = set()
    list_errors = 0
    for lu in portal.list_urls:
        try:
            html = _fetch(client, lu)
        except Exception as exc:  # noqa: BLE001
            list_errors += 1
            sys.stderr.write(f"[announce] {portal.key} 列表页失败 {lu}: {type(exc).__name__}\n")
            continue
        for item in parse_list(portal, lu, html):
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
    for item in candidates:
        if item.url in existing:
            if not dry_run:
                sb.table("announcement_postings").update(
                    {"last_seen_at": _now_iso(), "updated_at": _now_iso()}
                ).eq("source_url", item.url).execute()
            touched += 1
            continue
        # 新公告 → 抽详情
        try:
            dhtml = _fetch(client, item.url)
        except Exception as exc:  # noqa: BLE001
            detail_errors += 1
            sys.stderr.write(f"[announce] {portal.key} 详情失败 {item.url}: {type(exc).__name__}\n")
            continue
        dtext = _visible_text(dhtml)
        published = item.published_at or extract_published(dtext)
        deadline, deadline_text = extract_deadline(dtext, published_at=published)
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
        "touched": touched,
        "deadline_hit": deadline_hit,
        "list_errors": list_errors,
        "detail_errors": detail_errors,
    }
    if dry_run:
        metrics["dry_run_rows"] = new_rows
    return metrics


def run(portal_keys: list[str] | None, dry_run: bool) -> dict:
    portals = [PORTALS_BY_KEY[k] for k in portal_keys] if portal_keys else list(PORTALS)
    sb = None if dry_run else db.get_supabase()
    started = _now_iso()
    per_portal = []
    with _client() as client:
        for p in portals:
            m = harvest_portal(client, sb, p, dry_run)
            per_portal.append(m)
            print(f"[announce] {p.key}: 候选 {m['found']} / 新增 {m['new']} / 更新 {m['touched']} "
                  f"/ 抽到截止日 {m['deadline_hit']} / 列表错 {m['list_errors']} / 详情错 {m['detail_errors']}")

    total_new = sum(m["new"] for m in per_portal)
    total_found = sum(m["found"] for m in per_portal)
    total_err = sum(m["list_errors"] + m["detail_errors"] for m in per_portal)
    # 零产出出声：候选为 0 或全是错，别静默绿灯（工程化底线）。
    status = ops_runs.status_from_counts(processed=total_found, failed=total_err)
    if total_found == 0:
        status = "failed"
        print("::warning::[announce] 全部 portal 候选为 0 —— 疑似列表页形态变了或被拦")

    metrics = {
        "portals": [{k: v for k, v in m.items() if k != "dry_run_rows"} for m in per_portal],
        "total_found": total_found,
        "total_new": total_new,
        "total_deadline_hit": sum(m["deadline_hit"] for m in per_portal),
        "total_errors": total_err,
    }
    if not dry_run and sb is not None:
        ops_runs.record_ops_run(sb, "announcement_harvest", metrics,
                                status=status, started_at=started, finished_at=_now_iso())
    return {"per_portal": per_portal, "metrics": metrics}


def main() -> int:
    ap = argparse.ArgumentParser(description="公告抓取")
    ap.add_argument("--dry-run", action="store_true", help="只抓不写库，打印将入库的行")
    ap.add_argument("--portal", action="append", help="只跑指定 portal key，可多次")
    ap.add_argument("--no-expire", action="store_true", help="跳过过期治理")
    args = ap.parse_args()

    db.load_environment()
    result = run(args.portal, args.dry_run)

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
