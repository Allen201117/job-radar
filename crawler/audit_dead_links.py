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
from datetime import datetime, timezone
from urllib.parse import urlparse

import db
from playwright.sync_api import sync_playwright


def _now():
    return datetime.now(timezone.utc).isoformat()


# 需渲染判活的浏览器/SPA 源（JD 在 list 自带或详情 DOM；httpx detail-fetcher 覆盖不到）。
# 死活巡检按 adapter 精确锁定这些源，取代旧 fetch_sample 的「全库深翻页抽样」。
_BROWSER_ADAPTERS = ("moka", "beisen", "feishu")

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


def fetch_browser_liveness(sb, limit, shard="0/1", host_filter=None):
    """死活巡检队列（取代旧「全库深翻页抽样」fetch_sample）。

    旧法弊端：count(exact)+10 个 0~90% 偏移窗口抽样 → 深 OFFSET(0.9×13万)在大表上撞 statement_timeout、
    抽样随机且每轮重复检同一批、不记录已检（无滚动覆盖）。
    新法：只锁定浏览器源(adapter ∈ _BROWSER_ADAPTERS)的 active 岗，按 enrich_checked_at NULLS FIRST
    （从未探活的最先）取 limit 个；source_id 打头排序吃 migration 151 部分索引、脱离 statement_timeout。
    main() 每探一岗即盖 enrich_checked_at 时间戳 → 下轮自动取下一批，全量 ~N 轮滚动覆盖且持续保持新鲜，
    死岗一旦 expired 即离开 active 集、不再被取。shard=k/n 多进程并行互不重叠。"""
    k, n = (int(x) for x in shard.split("/"))
    src_ids = [s["id"] for s in
               ((sb.table("sources").select("id").in_("adapter_name", list(_BROWSER_ADAPTERS)).execute().data) or [])]
    if not src_ids:
        return []
    rows, page = [], 1000
    want = limit * n + 100  # 多取一些，shard 切片后仍够 limit
    for offset in range(0, 60000, page):
        chunk = (sb.table("jobs").select("id,title,company,jd_url")
                 .in_("source_id", src_ids).eq("status", "active")
                 # source_id 打头吃 151 (source_id, enrich_checked_at nulls first) WHERE active 索引（同 sweep）。
                 .order("source_id").order("enrich_checked_at", desc=False, nullsfirst=True)
                 .range(offset, offset + page - 1).execute().data) or []
        if host_filter:
            chunk = [r for r in chunk if host_filter in (host_of(r.get("jd_url")) or "")]
        rows.extend(chunk)
        if len(chunk) < page or len(rows) >= want:
            break
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
    apply = "--apply" in sys.argv
    host_filter = arg("--host")
    limit = int(arg("--limit", "1500"))   # 单 shard 单轮渲染上限，控 CI 时长（~3s/岗）
    shard = arg("--shard", "0/1")          # k/n 多进程并行互不重叠
    sweep_kw = arg("--sweep")  # 对「source_url 含 kw 的源」做全量逐岗审计，配 --apply 精确下架其失效岗
    sb = db.get_supabase()
    if sweep_kw:
        srcs = sb.table("sources").select("id,company").ilike("source_url", "%" + sweep_kw + "%").execute().data or []
        sample = []
        for s in srcs:
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
        sample = fetch_browser_liveness(sb, limit, shard, host_filter)
        print(f"[巡检] 浏览器源({'/'.join(_BROWSER_ADAPTERS)}) shard {shard} 认领 {len(sample)}（limit={limit}）")
    print(f"待渲染 {len(sample)} 条；模式={'APPLY(dead→expired + 盖巡检时间戳)' if apply else 'DRY-RUN(只报告)'}\n")

    apply_ok = [0]
    agg = defaultdict(lambda: {"dead": 0, "alive": 0, "suspect": 0, "unsure": 0})
    RESTART_EVERY = 40  # 每渲染这么多个重启浏览器，规避长跑内存泄漏/崩溃（智元 613 一次跑崩过）

    def mark(jid, dead):
        """探活后回写：dead→status='expired'；非 dead→只盖 enrich_checked_at（轮转，下轮取下一批）。
        非 apply 不写库（dry-run 只报告，不滚动）。"""
        patch = {"enrich_checked_at": _now()}
        if dead:
            patch["status"] = "expired"
        try:
            sb.table("jobs").update(patch).eq("id", jid).execute()
            if dead:
                apply_ok[0] += 1
        except Exception as e:
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
    N = sum(tot.values()) or 1
    print(f"\n合计 {N}: dead {tot['dead']}({tot['dead']*100//N}%) suspect {tot['suspect']}({tot['suspect']*100//N}%) "
          f"alive {tot['alive']}({tot['alive']*100//N}%) unsure {tot['unsure']}({tot['unsure']*100//N}%)")
    print("解读: dead=渲染出'职位不存在'类标记(高置信失效); suspect=渲染了但无标题(疑似/反爬,需人工); unsure=空/被拦(不下架)")
    if apply:
        print(f"\n[APPLY] 边扫边下架，共置 expired {apply_ok[0]} 条。")
    else:
        print("\n（DRY-RUN：未写库。加 --apply 增量下架 dead 项；suspect 默认不动。）")


if __name__ == "__main__":
    main()
