"""每日复验：把**正在展示**的每条公告真抓一遍正文，判它现在还能不能报，报不了就下架。

为什么不能只靠入库时那一次判断（2026-09-18 逐条 live 复核 118 条在展示的公告后立的碑）：
标题门只在首次入库那一刻看一眼标题，此后这行就一直 active 躺着。而现实是——
- 报名窗写在**正文**里，官方随时能另发一条公告把它提前关掉；
- 「…关闭报名系统公告」「…专业测试公告」「…面试确认公告」「…报名确认人数公告」「…岗位表」
  这些标题里都带「招聘」二字，入库时的正向门直接放行，点进去却是招聘流程末端的过程通知。
⇒ 判断必须每天在正文上重做一遍。这就是本模块。

与 expire.py 的分工：
- expire.py 只看**库里已有的字段**（deadline / published_at + TTL），不联网，快、但看不见正文里的变化。
- verify.py 真抓详情页、在正文上重判，并把抽到的新截止日写回去。两者互补，都保留。

⚠️ 安全闸：单轮下架比例超过 `_MAX_EXPIRE_FRACTION` 直接放弃写库并记 failed。
   判据是正则，正则改错一次就能把整页公告清空 —— 对齐岗位库 sweep 的 max_expire_fraction 先例。
⚠️ 抓不到（超时 / 连接失败）**一律不判死**，只是不更新：够不着不等于对方撤了
   （CLAUDE.md「『我没找到』不能升级成『它不存在』」）。只有 404/410 这种明确的「页面没了」才标 dead。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
from datetime import date, datetime, timezone

import httpx

import db  # noqa: E402
import ops_runs  # noqa: E402
from adapters.cn_portal_tls import make_transport  # noqa: E402

from .body import extract_body
from .classify import detect_audience, detect_employer_type
from .deadline import extract_published
from .portals import PORTALS, PORTALS_BY_KEY, detail_text
from .quality import assess

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# 单轮最多复验多少条（按 last_checked_at 最久未验优先轮转，其余留给下一轮）。
_BATCH = int(os.environ.get("ANNOUNCEMENT_VERIFY_BATCH", "400"))
# 政府站点，并发克制。
_WORKERS = int(os.environ.get("ANNOUNCEMENT_VERIFY_WORKERS", "6"))
# 单轮下架比例上限（超过即判为「判据出问题」，放弃写库）。
_MAX_EXPIRE_FRACTION = float(os.environ.get("ANNOUNCEMENT_VERIFY_MAX_EXPIRE", "0.5"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _client() -> httpx.Client:
    return httpx.Client(
        transport=make_transport(),
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9",
                 "Accept": "text/html,application/xhtml+xml,*/*"},
        timeout=25,
        follow_redirects=True,
    )


def _check_one(row: dict, today: date) -> dict:
    """抓一条 + 在正文上重判。返回 {row, outcome, reason, deadline, verdict}。"""
    portal = PORTALS_BY_KEY.get(row["source_portal"])
    if portal is None:
        # 本模块只会读 portals.py 里定义的 HTML 公告页。国聘那类 JSON 源不在这儿复验
        # （它的报名起止日是结构化字段，由 announcements/iguopin.py 每天重拉刷新），
        # 硬用 HTML 那套去读它的 SPA 空壳只会读出一堆垃圾。**不认识就不判**，别瞎判。
        return {"row": row, "outcome": "unsupported", "reason": "no_portal_definition"}
    referer = portal.list_urls[0] if portal else None
    try:
        with _client() as client:
            resp = client.get(row["source_url"], headers={"Referer": referer} if referer else None)
        if resp.status_code in (404, 410):
            return {"row": row, "outcome": "dead", "reason": "unreachable"}
        resp.raise_for_status()
        html = resp.content.decode(resp.encoding or "utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        # 够不着 ≠ 对方撤了 → 不判死，留到下一轮
        return {"row": row, "outcome": "skip", "reason": type(exc).__name__}

    full = detail_text(portal, html) if portal else html
    body = extract_body(full, row.get("title") or "")
    published = None
    if row.get("published_at"):
        try:
            published = date.fromisoformat(str(row["published_at"])[:10])
        except ValueError:
            published = None
    published = published or extract_published(body)

    v = assess(row.get("title") or "", body, published_at=published, today=today)
    return {
        "row": row,
        "outcome": "expire" if v.action == "reject" else "keep",
        "reason": v.reason,
        "verdict": "index_page" if v.action == "flag" else "ok",
        # 顺手刷新分面字段：存量是历次不同版本代码写的，实测库里 65 条 unknown
        # 用现在的代码重算只剩 24 条 —— 分面字段陈旧会让筛选器把能投的岗筛没。
        "audience": detect_audience((row.get("title") or "") + " " + body[:2000]),
        "employer_type": detect_employer_type(row.get("title") or ""),
        # 回填发布日：它是「没有截止日时靠什么过期」的锚点。库里 21 行两个日期都空，
        # TTL 只能从「今天首见」起算 —— 一条 1 月发的年度集中招聘会被当成新件再挂 45 天。
        "published_at": published.isoformat() if published else row.get("published_at"),
        # 抽不到就保留库里原值，别把已知的截止日清成 null
        "deadline": v.deadline.isoformat() if v.deadline else row.get("deadline"),
        "deadline_text": v.deadline_text or row.get("deadline_text"),
    }


def verify(sb, today: date | None = None, dry_run: bool = False, limit: int | None = None,
           only_ci_reachable: bool = False) -> dict:
    """复验在展示的公告。

    `only_ci_reachable=True` 只验 `PORTALS`（境外 runner 连得上的那几个省）。
    ⚠️ GitHub runner 连不上 `_GEO_BLOCKED_FROM_CI` 里的省，硬验它们 = 每条白等 25 秒超时，
    170 条就是 12 分钟空烧，很可能顶穿 job 时限把台账写不成。那些省由创始人 Mac 的 launchd 复验。
    """
    today = today or date.today()
    batch = limit or _BATCH
    rows = (sb.table("announcement_postings")
            .select("id, source_portal, source_url, title, published_at, deadline, "
                    "deadline_text, verdict, audience, employer_type")
            .eq("status", "active")
            .neq("source_portal", "iguopin")   # 见 _check_one：国聘由自己的 harvester 复验
            .order("last_checked_at", desc=False, nullsfirst=True)
            .limit(batch)
            .execute()).data or []
    if only_ci_reachable:
        reachable = {p.key for p in PORTALS}
        rows = [r for r in rows if r["source_portal"] in reachable]
    if not rows:
        return {"checked": 0, "expired": 0, "flagged": 0, "dead": 0, "unreachable": 0,
                "deadline_filled": 0, "facets_refreshed": 0, "unsupported": 0, "aborted": False}

    results = []
    with cf.ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        results = list(pool.map(lambda r: _check_one(r, today), rows))

    to_expire = [r for r in results if r["outcome"] == "expire"]
    to_dead = [r for r in results if r["outcome"] == "dead"]
    unreachable = [r for r in results if r["outcome"] == "skip"]
    unsupported = [r for r in results if r["outcome"] == "unsupported"]
    reachable = len(results) - len(unreachable) - len(unsupported)

    # 安全闸：判据（正则）改错一次就能把整页清空 → 下架比例异常就整轮放弃，不写库。
    aborted = False
    if reachable and (len(to_expire) + len(to_dead)) / reachable > _MAX_EXPIRE_FRACTION:
        aborted = True
        print(f"::warning::[announce-verify] 下架比例 "
              f"{(len(to_expire)+len(to_dead))}/{reachable} 超过闸值 {_MAX_EXPIRE_FRACTION}，本轮放弃写库")

    reasons: dict[str, int] = {}
    deadline_filled = flagged = refreshed = 0
    if not dry_run and not aborted:
        for r in results:
            row, patch = r["row"], {"last_checked_at": _now_iso(), "updated_at": _now_iso()}
            if r["outcome"] in ("skip", "unsupported"):
                continue  # 够不着 / 不归本模块管：连 last_checked_at 都不动
            if r["outcome"] in ("expire", "dead"):
                patch["status"] = "expired" if r["outcome"] == "expire" else "dead"
                patch["expire_reason"] = r["reason"]
                reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
            else:
                patch["verdict"] = r["verdict"]
                if r["verdict"] == "index_page":
                    flagged += 1
                for col in ("audience", "employer_type", "published_at"):
                    if r.get(col) and r[col] != row.get(col):
                        patch[col] = r[col]
                        refreshed += 1
                if r["deadline"] and r["deadline"] != row.get("deadline"):
                    patch["deadline"] = r["deadline"]
                    patch["deadline_text"] = r["deadline_text"]
                    if not row.get("deadline"):
                        deadline_filled += 1
            sb.table("announcement_postings").update(patch).eq("id", row["id"]).execute()
    else:
        for r in to_expire + to_dead:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        flagged = sum(1 for r in results if r.get("verdict") == "index_page")
        deadline_filled = sum(1 for r in results
                              if r["outcome"] == "keep" and r["deadline"] and not r["row"].get("deadline"))

    return {
        "checked": len(results),
        "expired": len(to_expire),
        "dead": len(to_dead),
        "flagged": flagged,
        "unreachable": len(unreachable),
        "unsupported": len(unsupported),   # 非 HTML 公告源（国聘），由各自的 harvester 复验
        "deadline_filled": deadline_filled,
        "facets_refreshed": refreshed,   # 分面字段（应届/社会、单位类型）被刷新的次数
        "reasons": reasons,
        "aborted": aborted,
        "details": [
            {"title": (r["row"].get("title") or "")[:60], "reason": r["reason"],
             "url": r["row"]["source_url"]}
            for r in to_expire + to_dead
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="公告每日复验（真抓正文，判还能不能报）")
    ap.add_argument("--dry-run", action="store_true", help="只判不写库，打印将下架的条目")
    ap.add_argument("--limit", type=int, default=None, help="本轮最多复验多少条")
    ap.add_argument("--only-ci-reachable", action="store_true",
                    help="只验境外 runner 连得上的省（GitHub CI 用；其余省由大陆 runner 复验）")
    args = ap.parse_args()

    db.load_environment()
    sb = db.get_supabase()
    started = _now_iso()
    m = verify(sb, dry_run=args.dry_run, limit=args.limit,
               only_ci_reachable=args.only_ci_reachable)
    print(f"[announce-verify] 复验 {m['checked']} / 下架 {m['expired']} / 死链 {m['dead']} "
          f"/ 汇总页标注 {m['flagged']} / 补到截止日 {m['deadline_filled']} "
          f"/ 刷新分面 {m['facets_refreshed']} / 够不着 {m['unreachable']} / 非本模块 {m['unsupported']}")
    if m.get("reasons"):
        print(f"[announce-verify] 下架原因：{m['reasons']}")
    for d in m.get("details", []):
        print(f"  ↓ [{d['reason']}] {d['title']}")
    if not args.dry_run:
        status = "failed" if m["aborted"] else ops_runs.status_from_counts(
            processed=m["checked"], failed=m["unreachable"])
        ops_runs.record_ops_run(sb, "announcement_verify",
                                {k: v for k, v in m.items() if k != "details"},
                                status=status, started_at=started, finished_at=_now_iso())
    return 1 if m["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
