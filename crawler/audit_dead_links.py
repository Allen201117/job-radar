#!/usr/bin/env python3
"""死链审计（无头浏览器）：抽样渲染 active 岗位的 jd_url，识别「软 404」(返回200但渲染'职位不存在/需登录/已下线')。

为什么要渲染：飞书/智阅(zhiye)/Moka/Workday 等 SPA 深链对访客返回 HTTP 200，但内容由 JS 渲染——
岗位已撤时页面渲染「职位不存在」之类，状态码查不出来（probe-dead-links.js 只能查硬 404=0.7%）。

判定（业界软 404 常用启发式）：渲染后取 body 文本，
  · 命中「不存在/已下线/已结束/已招满/not found/404」等标记 → dead（高置信，--apply 时下架）
  · 文本含岗位标题(前8字) 且无标记 → alive
  · 渲染出实质内容但无标题、无标记 → suspect（疑似，需人工复核，不自动下架）
  · 文本过短/疑似被反爬拦 → unsure（不下架）

选岗：浏览器源(moka/beisen/feishu) active 岗，按 enrich_checked_at 最旧优先轮转（取代旧深翻页抽样）；
每探一岗盖 enrich_checked_at 时间戳，下轮自动取下一批 → 全量滚动覆盖、持续保鲜。
用法：set -a; source ../.env.local; set +a
  python3 audit_dead_links.py                          # 轮转 dry-run，按 host 报告软404率
  python3 audit_dead_links.py --apply --limit 1500     # dead→expired + 盖时间戳轮转（生产用）
  python3 audit_dead_links.py --shard 0/6 --apply      # 多进程并行分片，互不重叠
  python3 audit_dead_links.py --host zhiye             # 只审某类 host(子串)
  python3 audit_dead_links.py --sweep agirobot --apply # 全量逐岗审计某源(source_url 子串)
只读为主；仅 --apply 写 status / enrich_checked_at。绝不打印密钥。
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import db
import jobs_db
import must_apply
import ops_runs
from playwright.sync_api import sync_playwright


def _now():
    return datetime.now(timezone.utc).isoformat()


# 需渲染判活的浏览器/SPA 源（JD 在 list 自带或详情 DOM；httpx detail-fetcher 覆盖不到、liveness-sweep 也管不了）。
# 死活巡检按 adapter 精确锁定这些源，取代旧 fetch_sample 的「全库深翻页抽样」。
# classify() 仅在命中 DEAD_MARKERS 才判 dead→下架（保守，不会误杀活岗）→ 多纳入 SPA 源是安全的纯增益。
# 注：wt/hotjob 有 httpx 撤岗检测（req_state=9501 / state=1017，走 liveness-sweep），故不在此列（无头慢且冗余）。
_BROWSER_ADAPTERS = (
    "moka", "beisen", "feishu",
    # 飞书同源变体（同一套 SPA，闭站标记与 feishu 一致）——之前漏配、零 liveness 覆盖。
    "nio_feishu", "xiaomi_feishu", "xpeng_feishu",
    # 自建/大厂 SPA 详情页：既无 httpx 撤岗检测、又不在 liveness-sweep → 此前完全无 liveness。
    # 闭站标记未逐站核实（best-effort）；命中 DEAD_MARKERS 才下架，不中也只是盖时间戳轮转，无副作用。
    "kuaishou", "byd", "bytedance", "bytedance_campus", "google",
    # 2026-06-25 补：db-report 实测 24h 覆盖=0 的大厂 SPA（alibaba 3789/netease 1177/ctrip 772/huawei 445 岗，
    # 之前不在任何保鲜流）。均为浏览器渲染详情页 → 纳入审计渲染探活（同上：命中 DEAD_MARKERS 才下架，否则只轮转盖戳）。
    "alibaba", "netease", "ctrip", "huawei",
    # 2026-06-25 补：bilibili（detail 端点需 ajSessionId cookie，httpx 拿不到 → 无快速撤岗信号）
    # → 走浏览器渲染探活兜底（社招深链 SPA，命中 DEAD_MARKERS 才下架）。phenom(AMD/百事)仍延后(SPA 壳+低相关)。
    "bilibili",
    # 2026-07-06 补：小红书/OPPO/百度是必投头部公司但无 httpx closure detector，详情页探活走通用软 404 渲染审计。
    "xiaohongshu", "oppo", "baidu",
)

DEAD_MARKERS = [
    "职位不存在", "岗位不存在", "该职位不存在", "职位已下线", "已下线", "职位已关闭",
    "岗位已关闭", "已结束", "停止招聘", "已招满", "职位已过期", "岗位不存在",
    "职位不见了", "page not found", "not found", "404", "this job is no longer",
    "position is no longer", "no longer available", "已失效", "招聘已结束",
]
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 这些 ATS 要么反爬挡无头(workday)、要么已有 enrich 的 httpx detail-fetcher 做撤岗检测(workday/oracle/greenhouse/lever/hotjob/...)，
# 无头审计读不准(false positive) 且无必要。默认跳过，把无头审计聚焦在 SPA 源(飞书/智阅/Moka/北森/公司自建站)。
# 加 --include-ats 可强制纳入。
ATS_SKIP = ("myworkdayjobs.com", "oraclecloud.com", "greenhouse.io", "lever.co",
            "hotjob.cn", "smartrecruiters.com", "eightfold.ai", "amazon.jobs",
            "pepsicojobs.com", "phenompeople", "avature")


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def host_of(u):
    try:
        return urlparse(u).netloc
    except Exception:
        return None


def _shard_rows(rows, limit, shard):
    k, n = (int(x) for x in shard.split("/"))
    return [r for i, r in enumerate(rows) if i % n == k][:limit]


def merge_must_apply_candidates(must_rows, regular_rows, limit, must_apply_only=False):
    """为什么：必投倾斜只占专属配额；剩余名额仍走原轮转，并排除已认领 id。"""
    if limit <= 0:
        return []
    must_quota = limit if must_apply_only else limit // 2
    rows, seen = [], set()
    for row in must_rows:
        if len(rows) >= must_quota:
            break
        jid = row.get("id")
        if jid in seen:
            continue
        rows.append(row)
        if jid:
            seen.add(jid)
    if must_apply_only:
        return rows[:limit]
    for row in regular_rows:
        if len(rows) >= limit:
            break
        jid = row.get("id")
        if jid in seen:
            continue
        rows.append(row)
        if jid:
            seen.add(jid)
    return rows


def _fetch_browser_rows_pg(jobs_conn, src_ids, want, host_filter=None, prioritize_new=False, must_patterns=None):
    where = ["source_id = any(%s::uuid[])", "status='active'"]
    params = [src_ids]
    if must_patterns:
        where.append("coalesce(company, '') ilike any(%s)")
        params.append(list(must_patterns))
    if prioritize_new:
        where.append("enrich_checked_at is null")
        where.append("first_seen_at >= now() - interval '48 hours'")
        order = "first_seen_at desc"
    else:
        order = "source_id, enrich_checked_at asc nulls first"
    params.append(want)
    rows = jobs_db.fetch_all(
        jobs_conn,
        "select id, title, company, jd_url from jobs where " + " and ".join(where) +
        f" order by {order} limit %s",
        tuple(params),
    )
    if host_filter:
        rows = [r for r in rows if host_filter in (host_of(r.get("jd_url")) or "")]
    return rows


def _fetch_browser_rows_supabase(sb, src_ids, want, host_filter=None, prioritize_new=False, must_patterns=None):
    rows, page = [], 1000
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat() if prioritize_new else None
    for offset in range(0, 60000, page):
        q = (sb.table("jobs").select("id,title,company,jd_url")
             .in_("source_id", src_ids).eq("status", "active"))
        if must_patterns:
            q = q.or_(",".join(f"company.ilike.{p}" for p in must_patterns))
        if prioritize_new:
            # 近 48h 新增且从未核验，新者优先。
            q = q.is_("enrich_checked_at", "null").gte("first_seen_at", cutoff_iso).order("first_seen_at", desc=True)
        else:
            # source_id 打头吃 151 (source_id, enrich_checked_at nulls first) WHERE active 索引（同 sweep）。
            q = q.order("source_id").order("enrich_checked_at", desc=False, nullsfirst=True)
        chunk = (q.range(offset, offset + page - 1).execute().data) or []
        if host_filter:
            chunk = [r for r in chunk if host_filter in (host_of(r.get("jd_url")) or "")]
        rows.extend(chunk)
        if len(chunk) < page or len(rows) >= want:
            break
    return rows[:want]


def fetch_browser_liveness(sb, limit, shard="0/1", host_filter=None, jobs_conn=None, prioritize_new=False,
                           must_apply_first=False, must_apply_only=False):
    """死活巡检队列（取代旧「全库深翻页抽样」fetch_sample）。

    旧法弊端：count(exact)+10 个 0~90% 偏移窗口抽样 → 深 OFFSET(0.9×13万)在大表上撞 statement_timeout、
    抽样随机且每轮重复检同一批、不记录已检（无滚动覆盖）。
    新法：只锁定浏览器源(adapter ∈ _BROWSER_ADAPTERS)的 active 岗，按 enrich_checked_at NULLS FIRST
    （从未探活的最先）取 limit 个；source_id 打头排序吃 migration 151 部分索引、脱离 statement_timeout。
    main() 每探一岗即盖 enrich_checked_at 时间戳 → 下轮自动取下一批，全量 ~N 轮滚动覆盖且持续保持新鲜，
    死岗一旦 expired 即离开 active 集、不再被取。shard=k/n 多进程并行互不重叠。

    prioritize_new（01 spec §3.1，消灭 7 天盲区）：只取**近 48h 新增且从未核验**的 SPA 岗（enrich_checked_at
    IS NULL 且 first_seen_at >= now()-48h），按 first_seen_at desc → 新灌入的坏岗高频小批先清，不必等 6 分片轮转一遍。"""
    k, n = (int(x) for x in shard.split("/"))
    src_ids = [s["id"] for s in
               ((sb.table("sources").select("id").in_("adapter_name", list(_BROWSER_ADAPTERS)).execute().data) or [])]
    if not src_ids:
        return []
    want = limit * n + 100  # 多取一些，shard 切片后仍够 limit
    fetch_rows = _fetch_browser_rows_pg if jobs_conn is not None else _fetch_browser_rows_supabase
    if must_apply_first or must_apply_only:
        pats = must_apply.patterns()
        if not pats:
            return [] if must_apply_only else fetch_browser_liveness(
                sb, limit, shard, host_filter, jobs_conn=jobs_conn, prioritize_new=prioritize_new
            )
        must_quota = limit if must_apply_only else limit // 2
        must_want = must_quota * n + 100
        fetch_args = (jobs_conn, src_ids) if jobs_conn is not None else (sb, src_ids)
        must_rows = fetch_rows(*fetch_args, must_want, host_filter=host_filter,
                               prioritize_new=prioritize_new, must_patterns=pats)
        must_shard = _shard_rows(must_rows, must_quota, shard)
        if must_apply_only:
            return merge_must_apply_candidates(must_shard, [], limit, must_apply_only=True)
        regular_want = (limit - len(must_shard)) * n + 100 + len(must_shard) * n
        regular_rows = fetch_rows(*fetch_args, max(want, regular_want), host_filter=host_filter,
                                  prioritize_new=prioritize_new)
        regular_shard = _shard_rows(regular_rows, limit, shard)
        return merge_must_apply_candidates(must_shard, regular_shard, limit)
    # jobs 已迁香港库：jobs_conn 给定时直连查；否则 Supabase 分页。
    if jobs_conn is not None:
        rows = _fetch_browser_rows_pg(jobs_conn, src_ids, want, host_filter=host_filter, prioritize_new=prioritize_new)
        return [r for i, r in enumerate(rows) if i % n == k][:limit]
    rows = _fetch_browser_rows_supabase(sb, src_ids, want, host_filter=host_filter, prioritize_new=prioritize_new)
    return [r for i, r in enumerate(rows) if i % n == k][:limit]


def classify(page, title):
    try:
        text = page.inner_text("body", timeout=4000) or ""
    except Exception:
        text = ""
    low = text.lower()
    for m in DEAD_MARKERS:
        if m in text or m.lower() in low:
            return "dead", m
    key = (title or "").strip()[:8]
    if key and key in text:
        return "alive", "title-present"
    if len(text.strip()) < 40:
        return "unsure", "empty/blocked"
    return "suspect", "title-absent"


def main():
    started_at = _now()
    apply = "--apply" in sys.argv
    host_filter = arg("--host")
    limit = int(arg("--limit", "1500"))   # 单 shard 单轮渲染上限，控 CI 时长（~3s/岗）
    shard = arg("--shard", "0/1")          # k/n 多进程并行互不重叠
    sweep_kw = arg("--sweep")  # 对「source_url 含 kw 的源」做全量逐岗审计，配 --apply 精确下架其失效岗
    prioritize_new = "--prioritize-new" in sys.argv  # 01 spec §3.1：只清近 48h 新增未核验 SPA 岗（高频小批，消灭 7 天盲区）
    must_apply_first = "--must-apply-first" in sys.argv
    must_apply_only = "--must-apply-only" in sys.argv
    sb = db.get_supabase()                                       # sources 走 Supabase
    jobs_conn = jobs_db.get_conn() if jobs_db.enabled() else None  # jobs 读写走香港库（Phase 1）
    if sweep_kw:
        srcs = sb.table("sources").select("id,company").ilike("source_url", "%" + sweep_kw + "%").execute().data or []
        sample = []
        for s in srcs:
            if jobs_conn is not None:
                sample.extend(jobs_db.fetch_all(
                    jobs_conn,
                    "select id, title, company, jd_url from jobs where status='active' and source_id = %s::uuid",
                    (s["id"],)))
                continue
            off = 0
            while True:
                rows = (sb.table("jobs").select("id,title,company,jd_url")
                        .eq("status", "active").eq("source_id", s["id"]).range(off, off + 999).execute().data or [])
                if not rows:
                    break
                sample.extend(rows)
                if len(rows) < 1000:
                    break
                off += 1000
        print(f"[SWEEP] 源含「{sweep_kw}」共 {len(srcs)} 个，全量逐岗 {len(sample)} 条")
    else:
        # 默认=浏览器源死活巡检轮转（enrich_checked_at 最旧优先，取代旧深翻页抽样）。
        # --prioritize-new：只取近 48h 新增未核验岗，高频小批清新岗（01 spec §3.1）。
        # --must-apply-first：先用最多 50% 分片容量保必投清单公司，再用原轮转补满；--must-apply-only 给高频小跑量专用。
        sample = fetch_browser_liveness(
            sb,
            limit,
            shard,
            host_filter,
            jobs_conn=jobs_conn,
            prioritize_new=prioritize_new,
            must_apply_first=must_apply_first,
            must_apply_only=must_apply_only,
        )
        if must_apply_only:
            mode_tag = "必投专用"
        elif must_apply_first:
            mode_tag = "必投优先+轮转"
        else:
            mode_tag = "新岗优先(48h未核验)" if prioritize_new else "轮转"
        print(f"[巡检-{mode_tag}] 浏览器源({'/'.join(_BROWSER_ADAPTERS)}) shard {shard} 认领 {len(sample)}（limit={limit}）")
    print(f"待渲染 {len(sample)} 条；模式={'APPLY(dead→expired + 盖巡检时间戳)' if apply else 'DRY-RUN(只报告)'}\n")

    apply_ok = [0]
    write_fail = [0]
    agg = defaultdict(lambda: {"dead": 0, "alive": 0, "suspect": 0, "unsure": 0})
    RESTART_EVERY = 40  # 每渲染这么多个重启浏览器，规避长跑内存泄漏/崩溃（智元 613 一次跑崩过）

    def mark(jid, dead):
        """探活后回写：dead→status='expired'；非 dead→只盖 enrich_checked_at（轮转，下轮取下一批）。
        非 apply 不写库（dry-run 只报告，不滚动）。"""
        patch = {"enrich_checked_at": _now()}
        if dead:
            patch["status"] = "expired"
        try:
            if jobs_conn is not None:
                cols = list(patch.keys())
                set_clause = ", ".join(f"{c} = %s" for c in cols)
                jobs_db.execute(jobs_conn, f"update jobs set {set_clause} where id = %s::uuid",
                                [patch[c] for c in cols] + [jid])
            else:
                sb.table("jobs").update(patch).eq("id", jid).execute()
            if dead:
                apply_ok[0] += 1
        except Exception as e:
            write_fail[0] += 1
            sys.stderr.write(f"\n  写失败 {jid}: {str(e)[:60]}\n")

    with sync_playwright() as p:
        hold = {"b": None, "pg": None}

        def fresh():
            try:
                if hold["b"]:
                    hold["b"].close()
            except Exception:
                pass
            hold["b"] = p.chromium.launch(headless=True)
            hold["pg"] = hold["b"].new_context(
                user_agent=UA, viewport={"width": 1280, "height": 900}).new_page()

        fresh()
        for i, j in enumerate(sample, 1):
            if i > 1 and i % RESTART_EVERY == 1:
                fresh()
            h = host_of(j["jd_url"])
            verdict, why = "unsure", "nav-fail"
            try:
                hold["pg"].goto(j["jd_url"], wait_until="domcontentloaded", timeout=20000)
                hold["pg"].wait_for_timeout(2500)  # 给 SPA 渲染时间
                verdict, why = classify(hold["pg"], j.get("title"))
            except Exception as e:
                verdict, why = "unsure", type(e).__name__
                try:
                    fresh()  # 可能浏览器崩了 → 重建后继续
                except Exception:
                    pass
            agg[h][verdict] += 1
            if apply:
                mark(j["id"], verdict == "dead")  # dead→下架；其余盖巡检时间戳轮转。边扫边写，中途崩了不丢
            sys.stderr.write(f"\r  {i}/{len(sample)} {verdict:7s} {h[:28]:28s} {why[:14]} exp={apply_ok[0]}")
        try:
            hold["b"].close()
        except Exception:
            pass
    sys.stderr.write("\n\n")

    rows = sorted(agg.items(), key=lambda kv: -(kv[1]["dead"] + kv[1]["suspect"]))
    tot = defaultdict(int)
    print("================ 软 404 审计（按 host，dead+suspect 降序）================")
    for h, a in rows:
        n = a["dead"] + a["alive"] + a["suspect"] + a["unsure"]
        for k in ("dead", "alive", "suspect", "unsure"):
            tot[k] += a[k]
        flag = " ⚠" if a["dead"] or a["suspect"] else ""
        print(f"  {h:40s} 共{n}  dead{a['dead']} suspect{a['suspect']} alive{a['alive']} unsure{a['unsure']}{flag}")
    checked = sum(tot.values())
    N = checked or 1
    print(f"\n合计 {N}: dead {tot['dead']}({tot['dead']*100//N}%) suspect {tot['suspect']}({tot['suspect']*100//N}%) "
          f"alive {tot['alive']}({tot['alive']*100//N}%) unsure {tot['unsure']}({tot['unsure']*100//N}%)")
    print("解读: dead=渲染出'职位不存在'类标记(高置信失效); suspect=渲染了但无标题(疑似/反爬,需人工); unsure=空/被拦(不下架)")
    if apply:
        print(f"\n[APPLY] 边扫边下架，共置 expired {apply_ok[0]} 条。")
        ops_runs.record_ops_run(
            sb,
            "dead_link_audit",
            {
                "checked": checked,
                "expired": apply_ok[0],
                "alive": tot["alive"],
                "suspect": tot["suspect"],
                "unsure": tot["unsure"],
                "failed": write_fail[0],
            },
            status=ops_runs.status_from_counts(checked, write_fail[0]),
            started_at=started_at,
            finished_at=_now(),
        )
    else:
        print("\n（DRY-RUN：未写库。加 --apply 增量下架 dead 项；suspect 默认不动。）")


if __name__ == "__main__":
    main()
