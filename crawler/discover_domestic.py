"""
本土 ATS 批量发现引擎 —— 「最高效扩源」的本土版（对标 probe.py 的外企 --discover）。

痛点：本土 moka/beisen/feishu/hotjob 是「每公司独立子域」，host 无法由公司名稳定推断，
此前只能逐家人工 WebSearch 找 slug → 极慢。本引擎用各平台的**确定性发现 oracle**，
对一串公司名 × 若干 slug/brand 猜测做**批量 live 探测**，只保留真返回岗位且 title 对得上
目标公司的源，再复用 probe.emit_sql 写迁移。符合 CLAUDE.md：禁猜 slug 入库——入库前提永远是
live 确认返回真实岗位 + 门户 title-verify（防张冠李戴）。

确定性 oracle（全部 httpx，零浏览器，沙箱可达）：
  feishu : GET  {slug}.jobs.feishu.cn/            -> 200 = 真租户（404 = 非客户）
           POST {slug}.jobs.feishu.cn/api/v1/search/job/posts -> 真实岗位（含 title，可自动 title-verify）
  hotjob : POST {brand}.hotjob.cn/wecruit/common/getSLD (sld=host)
           -> linkData.link 含 /SU.../pb/ = wecruit(suiteKey) ; 含 /wt/ = wt(BRAND)
           再调 listPosition / position/list -> 真实岗位（确认 suiteKey/BRAND 有效）
  beisen : GET  {slug}.zhiye.com/ -> <title> != "Not Found" 且含公司名 = 真租户（通配恒 200，靠 title 判真伪）
           岗位确认走 playwright BeisenAdapter（沙箱若不可launch，记 tenant-oracle 命中待 daily-crawl 确认）

用法（本机/CI，有网络）：
  cd crawler
  python3 discover_domestic.py --targets targets.json            # 只扫不写
  python3 discover_domestic.py --targets targets.json --emit 109  # 把确认源写迁移 109
  python3 discover_domestic.py --targets targets.json --platforms feishu,hotjob  # 只扫指定平台

targets.json: [{"company":"比亚迪","cn":"比亚迪","slugs":["byd","biyadi"],"industry":"汽车"}, ...]
  - company/cn: 用于 title-verify（张冠李戴 guard）与入库公司名
  - slugs: 同时用作 feishu/beisen 子域猜测 与 hotjob brand 猜测
"""
import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(__file__))

import httpx  # noqa: E402
import normalizer  # noqa: E402
from probe import emit_sql  # noqa: E402  复用迁移生成

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 8

# hotjob/wecruit 三渠道（页面文件 → recruitType）；wt 同口径 recruitType。
_HOTJOB_CHANNELS = [("social.html", 2), ("school.html", 1), ("interns.html", 12)]
_WT_RECRUIT = [("social", 2), ("campus", 1), ("intern", 12)]


def _client():
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,en;q=0.9"})


def _title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html or "", re.S | re.I)
    return (m.group(1).strip() if m else "")


# 公司核心 token：取中文名去掉常见后缀，用于 title-verify 模糊匹配。
_CN_STOP = ("集团", "股份", "有限公司", "有限", "公司", "控股", "科技", "招聘", "官网", "官方",
            "校园招聘", "社会招聘", "校招", "社招")


def _core_tokens(cn: str):
    """生成用于 title 包含判断的核心子串（递进剥离后缀）。"""
    cn = (cn or "").strip()
    toks = set()
    if cn:
        toks.add(cn)
        stripped = cn
        for s in _CN_STOP:
            stripped = stripped.replace(s, "")
        stripped = stripped.strip()
        if len(stripped) >= 2:
            toks.add(stripped)
        # 头 2~4 字也作为弱匹配（如「比亚迪」「潍柴」）
        if len(cn) >= 2:
            toks.add(cn[:2])
        if len(cn) >= 3:
            toks.add(cn[:3])
    return {t for t in toks if len(t) >= 2}


def _verify(title_or_text: str, cn: str) -> bool:
    """张冠李戴 guard：门户/岗位文本含公司核心 token 之一。"""
    text = title_or_text or ""
    for t in _core_tokens(cn):
        if t and t in text:
            return True
    return False


# ───────────────────────── feishu ─────────────────────────
def feishu_probe(slug: str, cn: str):
    """GET 租户 + POST posts。返回 dict 或 None。"""
    host = f"{slug}.jobs.feishu.cn"
    try:
        with _client() as cli:
            r = cli.get(f"https://{host}/")
            if r.status_code != 200:
                return None  # 404 = 非飞书客户
            portal_title = _title(r.text)
            # posts API（host 级，与 portal 无关）
            body = {"keyword": "", "limit": 20, "offset": 0, "job_category_id_list": [],
                    "tag_id_list": [], "location_code_list": [], "subject_id_list": [],
                    "recruitment_id_list": [], "portal_type": 2, "job_function_id_list": [],
                    "storefront_id": ""}
            pr = cli.post(f"https://{host}/api/v1/search/job/posts", json=body,
                          headers={"Content-Type": "application/json",
                                   "Referer": f"https://{host}/index/position"})
            posts = ((pr.json().get("data") or {}).get("job_post_list")) or []
    except Exception as e:
        return {"err": f"{type(e).__name__}"}
    titles = [str(p.get("title") or "") for p in posts][:5]
    # title-verify：门户标题或岗位文本含公司名（飞书岗位含 city/部门，公司名常不在岗位标题里，
    # 故以门户标题为主判据）
    verified = _verify(portal_title, cn) or any(_verify(t, cn) for t in titles)
    return {"platform": "feishu", "host": host, "count": len(posts),
            "portal_title": portal_title, "titles": titles, "verified": verified,
            "url": f"https://{host}/index/position"}


# ───────────────────────── hotjob / wt ─────────────────────────
def _getsld(brand: str):
    host = f"{brand}.hotjob.cn"
    try:
        with _client() as cli:
            r = cli.post(f"https://{host}/wecruit/common/getSLD", data={"sld": host},
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            if r.status_code != 200:
                return None
            link = (((r.json().get("data") or {}).get("linkData") or {}).get("link")) or ""
            return link or None
    except Exception:
        return None


def _hotjob_count(origin: str, suite_key: str, recruit_type: int) -> int:
    try:
        with _client() as cli:
            r = cli.post(f"{origin}/wecruit/positionInfo/listPosition/{suite_key}",
                         data={"recruitType": recruit_type, "currentPage": 1, "pageSize": 20},
                         headers={"Content-Type": "application/x-www-form-urlencoded",
                                  "Referer": f"{origin}/{suite_key}/pb/social.html", "Origin": origin})
            pf = ((r.json().get("data") or {}).get("pageForm") or {})
            return int(pf.get("totalCount") or pf.get("recordCount") or len(pf.get("pageData") or []))
    except Exception:
        return 0


def _wt_count_and_sample(origin: str, brand: str, recruit_type: int):
    try:
        with _client() as cli:
            r = cli.get(f"{origin}/wt/{brand}/web/json/position/list",
                        params={"brandCode": 1, "recruitType": recruit_type, "page": 1})
            j = r.json()
            posts = j.get("postList") or []
            return int(j.get("rowCount") or len(posts)), [str(p.get("postName") or "") for p in posts[:5]]
    except Exception:
        return 0, []


def wt_probe(brand: str, cn: str):
    """wt(老版 WinTalent) 直连发现 oracle（getSLD 对 wt 返 HTML 不可用，改直接探 list API）。
    host={brand}.hotjob.cn，BRAND 大小写因租户而异（yili 小写 / CGN/CT/HMGC 大写）→ 试两种。
    命中即同时拿到岗位数（自带 job-confirm）。"""
    host = f"{brand}.hotjob.cn"
    for wb in (brand, brand.upper()):
        try:
            with _client() as cli:
                r = cli.get(f"https://{host}/wt/{wb}/web/json/position/list",
                            params={"brandCode": 1, "recruitType": 2, "page": 1})
                if r.status_code != 200:
                    continue
                j = r.json()
        except Exception:
            continue
        posts = j.get("postList") or []
        cnt = int(j.get("rowCount") or len(posts))
        if cnt > 0:
            origin = f"https://{host}"
            titles = [str(p.get("postName") or "") for p in posts[:5]]
            return {"platform": "wt", "origin": origin, "host": host, "wt_brand": wb,
                    "count": cnt, "titles": titles, "verified": True}
    return None


def hotjob_probe(brand: str, cn: str):
    link = _getsld(brand)
    if not link:
        return None
    p = httpx.URL(link)
    origin = f"{p.scheme}://{p.host}"
    parts = [s for s in (p.path or "").split("/") if s]
    if not parts:
        return None
    if parts[0].startswith("SU"):  # wecruit
        suite_key = parts[0]
        channels = []
        for page, rt in _HOTJOB_CHANNELS:
            n = _hotjob_count(origin, suite_key, rt)
            channels.append((page, rt, n))
        total = sum(n for _, _, n in channels)
        if total == 0:
            return {"platform": "wecruit", "host": p.host, "count": 0, "verified": False, "note": "no jobs"}
        return {"platform": "wecruit", "origin": origin, "host": p.host, "suite_key": suite_key,
                "channels": channels, "count": total, "verified": True}  # suiteKey 来自官方域名，verified
    if parts[0].lower() == "wt" and len(parts) >= 2:  # wt
        wt_brand = parts[1]
        chans = []
        sample = []
        for chan, rt in _WT_RECRUIT:
            n, s = _wt_count_and_sample(origin, wt_brand, rt)
            chans.append((chan, rt, n))
            sample += s
        total = sum(n for _, _, n in chans)
        if total == 0:
            return {"platform": "wt", "host": p.host, "count": 0, "verified": False, "note": "no jobs"}
        return {"platform": "wt", "origin": origin, "host": p.host, "wt_brand": wt_brand,
                "channels": chans, "count": total, "titles": sample[:5], "verified": True}
    return None


# ───────────────────────── beisen ─────────────────────────
def beisen_probe(slug: str, cn: str):
    host = f"{slug}.zhiye.com"
    try:
        with _client() as cli:
            r = cli.get(f"https://{host}/")
            title = _title(r.text)
    except Exception:
        return None
    if not title or title.lower() in ("not found", "404", "404 not found"):
        return None  # 非北森租户
    verified = _verify(title, cn)
    return {"platform": "beisen", "host": host, "title": title, "verified": verified,
            "url_social": f"https://{host}/social", "url_campus": f"https://{host}/campus",
            "count": None}  # 岗位确认走 playwright，由 --confirm-beisen 或 daily-crawl 兜底


# ───────────────────────── sweep（并发） ─────────────────────────
def _probe_company(t, platforms):
    """单公司：逐 slug 探各平台，每平台命中即止。返回该公司的 hits 列表。"""
    company = t.get("company") or t.get("cn") or ""
    cn = t.get("cn") or company
    industry = t.get("industry") or ""
    slugs = t.get("slugs") or []
    out = []
    found = set()
    for slug in slugs:
        if "feishu" in platforms and "feishu" not in found:
            r = feishu_probe(slug, cn)
            if r and r.get("count", 0) > 0:
                r.update(company=company, cn=cn, industry=industry, slug=slug)
                out.append(r); found.add("feishu")
        if "hotjob" in platforms and not ({"wecruit", "wt"} & found):
            r = hotjob_probe(slug, cn) or wt_probe(slug, cn)  # getSLD 漏 wt → wt 直连 list 兜底
            if r and r.get("count", 0) > 0:
                r.update(company=company, cn=cn, industry=industry, slug=slug)
                out.append(r); found.add(r["platform"])
        if "beisen" in platforms and "beisen" not in found:
            r = beisen_probe(slug, cn)
            if r:
                r.update(company=company, cn=cn, industry=industry, slug=slug)
                out.append(r); found.add("beisen")
    return out


def sweep(targets, platforms, workers=12):
    """公司间并发（各公司独立、纯 httpx，I/O-bound）。"""
    hits = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe_company, t, platforms): t for t in targets}
        for fut in as_completed(futs):
            done += 1
            try:
                hits.extend(fut.result())
            except Exception:
                pass
            if done % 50 == 0:
                print(f"  ...{done}/{len(targets)} 公司已扫，命中 {len(hits)}", flush=True)
    return hits


def to_passed(hits):
    """feishu/wecruit/wt 命中 → probe.emit_sql 可消费的 passed 列表（已 httpx job-confirm，直接入迁移）。
    beisen 不在此（仅 tenant-verify，需 playwright 确认岗位，走 to_beisen_candidates）。"""
    passed = []
    for h in hits:
        company, industry = h["company"], h.get("industry", "")
        plat = h["platform"]
        if plat == "feishu" and h.get("verified") and h.get("count", 0) > 0:
            passed.append({"company": company, "adapter": "feishu", "url": h["url"],
                           "industry": industry, "segment": "private",
                           "_valid": h["count"], "_china": h["count"]})
        elif plat == "wecruit" and h.get("verified"):
            origin, sk = h["origin"], h["suite_key"]
            for page, rt, n in h["channels"]:
                if n > 0:
                    passed.append({"company": company, "adapter": "hotjob",
                                   "url": f"{origin}/{sk}/pb/{page}", "industry": industry,
                                   "segment": "private", "_valid": n, "_china": n})
        elif plat == "wt" and h.get("verified"):
            origin, wb = h["origin"], h["wt_brand"]
            # wt 一条入口源覆盖三渠道（adapter 内部遍历 recruitType）
            passed.append({"company": company, "adapter": "wt",
                           "url": f"{origin}/wt/{wb}/web/index", "industry": industry,
                           "segment": "private", "_valid": h["count"], "_china": h["count"]})
    return passed


def to_beisen_candidates(hits):
    """beisen tenant-verified 命中 → probe.py 候选格式（/social + /campus），交 probe --all 逐家 playwright
    job-confirm，只把真返回岗位的入库（区分老版可抽 / 新版需 adapter 升级）。"""
    cands = []
    for h in hits:
        if h.get("platform") != "beisen" or not h.get("verified"):
            continue
        for url in (h["url_social"], h["url_campus"]):
            cands.append({"company": h["company"], "adapter": "beisen", "url": url,
                          "industry": h.get("industry", ""), "segment": "private"})
    return cands


def main():
    ap = argparse.ArgumentParser(description="本土 ATS 批量发现引擎")
    ap.add_argument("--targets", required=True, help="目标 JSON 文件")
    ap.add_argument("--platforms", default="feishu,hotjob,beisen", help="逗号分隔: feishu,hotjob,beisen")
    ap.add_argument("--emit", default=None, help="写迁移前缀如 109（仅 verified 命中）")
    args = ap.parse_args()

    with open(args.targets, encoding="utf-8") as f:
        targets = json.load(f)
    platforms = {p.strip() for p in args.platforms.split(",") if p.strip()}

    print(f"[discover] 扫描 {len(targets)} 公司 × 平台 {sorted(platforms)} ...\n", flush=True)
    hits = sweep(targets, platforms)

    # 评审表（张冠李戴 review）：company | platform | slug | jobs | verified | title/sample
    print(f"\n{'公司':16} {'平台':8} {'slug':14} {'岗位':>5} {'核验':4} 门户标题/样例")
    print("-" * 100)
    for h in sorted(hits, key=lambda x: (not x.get("verified"), x["company"])):
        cnt = h.get("count")
        cnt = "?" if cnt is None else cnt
        vt = "✓" if h.get("verified") else "✗张?"
        tt = h.get("portal_title") or h.get("title") or (", ".join(h.get("titles", []))[:50])
        print(f"{h['company'][:15]:16} {h['platform']:8} {h['slug'][:13]:14} {str(cnt):>5} {vt:4} {tt[:46]}")

    passed = to_passed(hits)                 # feishu/wecruit/wt（已 job-confirm）
    beisen_cands = to_beisen_candidates(hits)  # beisen（待 playwright 确认）
    verified_companies = {h["company"] for h in hits if h.get("verified")}
    by_plat = {}
    for h in hits:
        by_plat[h["platform"]] = by_plat.get(h["platform"], 0) + 1
    print(f"\n[discover] 命中 {len(hits)} 条 {by_plat} / verified 公司 {len(verified_companies)}")
    print(f"[discover] feishu/wt/wecruit 待写源行 {len(passed)} / beisen 待确认候选 {len(beisen_cands)//2} 家")
    rej = sorted({h["company"] for h in hits if not h.get("verified")})
    if rej:
        print(f"[discover] ✗未过 title-verify（人工复核，疑张冠李戴）: {', '.join(rej)}")

    # 跨公司 URL 撞车检测：同一 source_url 被多个不同公司名认领 = slug 撞了别家 → 必人工复核
    # （wt/wecruit 按域名 verified，挡不住「我猜的 slug 恰是另一家的 brand」，如 yutong=宇通≠宇瞳光学）
    from collections import defaultdict
    url_companies = defaultdict(set)
    for p in passed:
        url_companies[p["url"]].add(p["company"])
    collisions = {u: cs for u, cs in url_companies.items() if len(cs) > 1}
    if collisions:
        print("[discover] ⚠️  URL 撞车（必人工复核，同名/同集团可留，异公司=张冠李戴需删）:")
        for u, cs in sorted(collisions.items()):
            print(f"      {u} ← {', '.join(sorted(cs))}")

    # beisen 候选写文件，交 probe.py --all 逐家 playwright job-confirm（仅当本次探了 beisen，避免清空旧候选）
    if "beisen" in platforms:
        bpath = os.path.join(os.path.dirname(__file__), "beisen_candidates.json")
        with open(bpath, "w", encoding="utf-8") as f:
            json.dump(beisen_cands, f, ensure_ascii=False, indent=1)
        print(f"[discover] beisen 候选已写 {os.path.relpath(bpath)} → 跑: "
              f"python3 confirm_beisen_parallel.py beisen_candidates.json <NNN> 6")

    if args.emit and passed:
        path = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                            f"{args.emit}_seed_probed_sources.sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(emit_sql(args.emit, passed))
        print(f"[discover] 已写 {os.path.relpath(path)}（{len(passed)} 源行，feishu/wt/wecruit）。push 后自动迁移。")
    elif args.emit:
        print("[discover] 无 feishu/wt/wecruit 命中，未写迁移（beisen 候选仍已导出）。")


if __name__ == "__main__":
    main()
