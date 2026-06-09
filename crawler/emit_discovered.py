"""把 subagent 找到的 discovered_urls.json 逐条 live 确认 + 写迁移。
feishu/hotjob/wt 走 httpx 确认（discover_domestic 的 probe 函数）；moka 走 MokaAdapter(playwright,
app.mokahr.com 沙箱可达)。只把**真返回岗位**且 title-verify 过的入库（防张冠李戴 + 禁猜入库）。

用法：python3 emit_discovered.py discovered_urls.json 112 [workers]
discovered_urls.json: [{company,cn,platform(moka|feishu|hotjob|wt),url?|slug?,industry}]
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))
import probe  # noqa: E402
import discover_domestic as dd  # noqa: E402


def _confirm_httpx(item):
    """feishu/hotjob/wt：httpx 确认，返回 passed-row 或 None。"""
    cn = item.get("cn") or item.get("company")
    company = item.get("company")
    industry = item.get("industry", "")
    plat = item.get("platform")
    slug = item.get("slug") or ""
    if plat == "feishu":
        if not slug and item.get("url"):
            slug = item["url"].split(".jobs.feishu.cn")[0].split("//")[-1]
        r = dd.feishu_probe(slug, cn)
        if r and r.get("count", 0) > 0 and r.get("verified"):
            return {"company": company, "adapter": "feishu", "url": r["url"],
                    "industry": industry, "segment": "private", "_valid": r["count"], "_china": r["count"]}
    elif plat in ("hotjob", "wt"):
        r = dd.hotjob_probe(slug, cn) or dd.wt_probe(slug, cn)
        if r and r.get("count", 0) > 0:
            if r["platform"] == "wt":
                return {"company": company, "adapter": "wt",
                        "url": f"{r['origin']}/wt/{r['wt_brand']}/web/index", "industry": industry,
                        "segment": "private", "_valid": r["count"], "_china": r["count"]}
            rows = []
            for page, rt, n in r["channels"]:
                if n > 0:
                    rows.append({"company": company, "adapter": "hotjob",
                                 "url": f"{r['origin']}/{r['suite_key']}/pb/{page}", "industry": industry,
                                 "segment": "private", "_valid": n, "_china": n})
            return rows or None
    return None


def _confirm_moka(item):
    """moka：MokaAdapter(playwright) 确认 app.mokahr.com/apply/{slug}/{orgId}。"""
    url = item.get("url")
    if not url:
        return None
    company = item.get("company")
    r = probe.probe_one({"company": company, "adapter": "moka", "url": url}, timeout=40)
    if r.get("valid", 0) > 0:
        return {"company": company, "adapter": "moka", "url": url,
                "industry": item.get("industry", ""), "segment": "private",
                "_valid": r["valid"], "_china": r["valid"]}
    return None


def main():
    path, prefix = sys.argv[1], sys.argv[2]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    with open(path, encoding="utf-8") as f:
        items = json.load(f)
    httpx_items = [i for i in items if i.get("platform") in ("feishu", "hotjob", "wt")]
    moka_items = [i for i in items if i.get("platform") == "moka"]
    passed = []

    # feishu/hotjob/wt：并发 httpx
    print(f"[emit-disc] httpx 确认 {len(httpx_items)} (feishu/hotjob/wt) ...", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fut in as_completed([ex.submit(_confirm_httpx, i) for i in httpx_items]):
            r = fut.result()
            if isinstance(r, list):
                passed.extend(r)
            elif r:
                passed.append(r)

    # moka：playwright 多进程并发（app.mokahr.com 沙箱可达；进程隔离避免 sync_playwright 冲突）
    print(f"[emit-disc] moka 确认 {len(moka_items)} (playwright, 多进程) ...", flush=True)
    if moka_items:
        from multiprocessing import Pool
        with Pool(5) as p:
            moka_results = p.map(_confirm_moka, moka_items)
        for i, r in zip(moka_items, moka_results):
            print(f"  {'✓' if r else '✗'} moka {i.get('company')}"
                  f"{(' '+str(r['_valid'])+'岗') if r else ''}", flush=True)
            if r:
                passed.append(r)

    # 撞车复核
    from collections import defaultdict
    uc = defaultdict(set)
    for p in passed:
        uc[p["url"]].add(p["company"])
    coll = {u: cs for u, cs in uc.items() if len(cs) > 1}
    if coll:
        print("[emit-disc] ⚠️ URL 撞车（复核）:", coll)

    won = sorted({p["company"] for p in passed})
    print(f"\n[emit-disc] 确认源行 {len(passed)} / 公司 {len(won)}: {', '.join(won)}")
    if passed:
        out = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                           f"{prefix}_seed_probed_sources.sql")
        with open(out, "w", encoding="utf-8") as f:
            f.write(probe.emit_sql(prefix, passed))
        print(f"[emit-disc] 已写 {os.path.relpath(out)}")


if __name__ == "__main__":
    main()
