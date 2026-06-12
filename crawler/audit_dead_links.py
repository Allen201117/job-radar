#!/usr/bin/env python3
"""死链审计（无头浏览器）：抽样渲染 active 岗位的 jd_url，识别「软 404」(返回200但渲染'职位不存在/需登录/已下线')。

为什么要渲染：飞书/智阅(zhiye)/Moka/Workday 等 SPA 深链对访客返回 HTTP 200，但内容由 JS 渲染——
岗位已撤时页面渲染「职位不存在」之类，状态码查不出来（probe-dead-links.js 只能查硬 404=0.7%）。

判定（业界软 404 常用启发式）：渲染后取 body 文本，
  · 命中「不存在/已下线/已结束/已招满/not found/404」等标记 → dead（高置信，--apply 时下架）
  · 文本含岗位标题(前8字) 且无标记 → alive
  · 渲染出实质内容但无标题、无标记 → suspect（疑似，需人工复核，不自动下架）
  · 文本过短/疑似被反爬拦 → unsure（不下架）

用法：set -a; source ../.env.local; set +a
  python3 audit_dead_links.py                 # 抽样 dry-run，按 host 报告软404率
  python3 audit_dead_links.py --per-host 6 --max 200
  python3 audit_dead_links.py --host zhiye    # 只审某类 host(子串)
  python3 audit_dead_links.py --apply         # 把 marker 确认 dead 的岗位置 status='expired'
只读为主；仅 --apply 写 status。绝不打印密钥。
"""
import sys
from collections import defaultdict
from urllib.parse import urlparse

import db
from playwright.sync_api import sync_playwright

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


def fetch_sample(sb, per_host, max_total, host_filter, include_ats):
    """跨全库分散窗口抽样，按 host 分桶，每 host 最多 per_host 条。默认跳过 ATS_SKIP(无头读不准/有enrich兜)。"""
    head = sb.table("jobs").select("id", count="exact", head=True).eq("status", "active").execute()
    n = head.count or 0
    windows = [int(f * max(0, n - 1000)) for f in
               (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)]
    by_host = defaultdict(list)
    seen_off = set()
    for off in windows:
        if off in seen_off:
            continue
        seen_off.add(off)
        rows = (sb.table("jobs").select("id,title,company,jd_url")
                .eq("status", "active").order("first_seen_at", desc=True)
                .range(off, off + 999).execute().data or [])
        for j in rows:
            h = host_of(j.get("jd_url"))
            if not h:
                continue
            if host_filter and host_filter not in h:
                continue
            if not include_ats and any(s in h for s in ATS_SKIP):
                continue
            if len(by_host[h]) < per_host:
                by_host[h].append(j)
    sample = [j for arr in by_host.values() for j in arr]
    return sample[:max_total], len(by_host)


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
    per_host = int(arg("--per-host", "5"))
    max_total = int(arg("--max", "180"))
    host_filter = arg("--host")

    include_ats = "--include-ats" in sys.argv
    sweep_kw = arg("--sweep")  # 对「source_url 含 kw 的源」做全量逐岗审计(不抽样)，配 --apply 精确下架其失效岗
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
        n_hosts = len(srcs)
        print(f"[SWEEP] 源含「{sweep_kw}」共 {len(srcs)} 个，全量逐岗 {len(sample)} 条")
    else:
        sample, n_hosts = fetch_sample(sb, per_host, max_total, host_filter, include_ats)
    print(f"抽样 {len(sample)} 条，覆盖 {n_hosts} 个 host；模式={'APPLY(写expired)' if apply else 'DRY-RUN(只报告)'}\n")

    agg = defaultdict(lambda: {"dead": 0, "alive": 0, "suspect": 0, "unsure": 0, "ids_dead": []})
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        for i, j in enumerate(sample, 1):
            h = host_of(j["jd_url"])
            verdict, why = "unsure", "nav-fail"
            try:
                page.goto(j["jd_url"], wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2500)  # 给 SPA 渲染时间
                verdict, why = classify(page, j.get("title"))
            except Exception as e:
                verdict, why = "unsure", type(e).__name__
            a = agg[h]
            a[verdict] += 1
            if verdict == "dead":
                a["ids_dead"].append(j["id"])
            sys.stderr.write(f"\r  {i}/{len(sample)}  {verdict:7s} {h[:32]:32s} {why[:18]}")
        browser.close()
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
        dead_ids = [i for a in agg.values() for i in a["ids_dead"]]
        print(f"\n[APPLY] 将 {len(dead_ids)} 条 marker 确认 dead 的岗位置 status='expired' …")
        ok = 0
        for jid in dead_ids:
            try:
                sb.table("jobs").update({"status": "expired"}).eq("id", jid).execute()
                ok += 1
            except Exception as e:
                print("  写失败", jid, str(e)[:80])
        print(f"[APPLY] 完成，置 expired {ok} 条。")
    else:
        print("\n（DRY-RUN：未写库。确认无误后加 --apply 下架 dead 项。suspect 项默认不动。）")


if __name__ == "__main__":
    main()
