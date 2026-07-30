"""抓取企业 logo（favicon）→ base64 存 company_logos。海外 CI 跑（能直连境外 favicon 服务）。

公司范围 = sources.company ∪ 必投清单品牌短名（lib/must-apply-list.json 的 name）。
后者是校招专区/看板的展示名，不在 sources 里 → 不补进来这些卡就永远是首字母兜底。

来源与质量门（见 CLAUDE.md「企业 logo」）：
- 三源取最清晰者，都过「是不是图片」内容嗅探门（站点 /favicon.ico 常返 HTML 错误页）：
  1. DuckDuckGo（icons.duckduckgo.com）—— live 实测无重复 md5，有就是真 logo，但多为小图、收录率低（65/205）；
  2. 公司官网自有图标（apple-touch-icon > icon > /favicon.ico）—— 覆盖率主力（166/205）、常是 180px 大图、公司自证；
  3. icon.horse —— 仅前两路都空时兜底，必须过占位门（它的 fallback 是按域名首字符生成的字母头像）。
- 存 data URI（base64）：国内直连境外 favicon 服务会被墙，必须抓下来跟着我们域名走。
- 域名推导不出时（飞书/北森/moka/workday 等平台托管）→ 用 URL 里的公司 slug 猜品牌域名，
  并抓首页做**页面核验**（页面自证属于该公司才认），防张冠李戴；核验不过就首字母兜底。

用法：python3 fetch_company_logos.py [--limit N] [--force] [--refetch-not-found]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

import must_apply
from db import get_sources, get_supabase
from logo_util import (
    COMPANY_DOMAIN_OVERRIDES,
    build_data_uri,
    candidate_domains,
    domain_for_company,
    icon_link_urls,
    icon_score,
    is_image_bytes,
    is_placeholder,
    page_verifies_company,
    placeholder_probe_domains,
    platform_slug,
)

_TIMEOUT = 15.0
# 抓公司官网首页/图标的超时。⚠️ 别再压到 6s：并发下国内站点 TLS 握手常超 6s，
# 一超时就会把「其实有真 logo 的公司」误判成 not_found（live 踩过：吉利/恒瑞/劲仔并发跑全灭、串行跑都有图）。
_HOME_TIMEOUT = 10.0
_FRESH_DAYS = 30
_SMALL_WIDTH = 48          # 已有图窄于此 → 继续找更清晰的来源（站点大图 / icon.horse）
_MAX_BYTES = 200_000       # favicon 不该更大；超过视为异常，不入库（首字母兜底）
_WORKERS = 4               # 并发抓取的公司数（8 并发实测误判率高：见 _HOME_TIMEOUT 注释）
_DDG = "https://icons.duckduckgo.com/ip3/{domain}.ico"
_ICON_HORSE = "https://icon.horse/icon/{domain}"


def _get(client: httpx.Client, url: str, timeout: Optional[float] = None) -> Optional[httpx.Response]:
    """带重试的 GET。重试间小睡一下：并发下连续两次瞬时失败很常见，不退避等于没重试。"""
    for attempt in range(2):
        try:
            return client.get(url) if timeout is None else client.get(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                print(f"[logo] 请求失败 {url}: {e}", file=sys.stderr)
                return None
            time.sleep(0.6)
    return None


def collect_placeholder_fingerprints(client: httpx.Client) -> set:
    """抓一批必然不存在的域名的 icon.horse 图，其 md5 即占位指纹（用于后续过滤）。

    占位图按域名首字符生成字母头像 → 必须 a-z0-9 各取一遍，否则漏掉的字母会被当成真 logo 入库。
    """
    prints = set()
    for d in placeholder_probe_domains():
        r = _get(client, _ICON_HORSE.format(domain=d))
        if r is not None and r.status_code == 200 and r.content:
            prints.add(hashlib.md5(r.content).hexdigest())
    return prints


def _candidate(content: bytes, content_type: Optional[str], source: str) -> Optional[dict]:
    """把一次抓取结果收敛成候选图（过大小门 + 图片内容嗅探），不合格返回 None。"""
    if not content or len(content) > _MAX_BYTES or not is_image_bytes(content):
        return None
    return {
        "bytes": content,
        "content_type": content_type,
        "width": icon_score(content_type, content),
        "source": source,
    }


def fetch_site_icon(client: httpx.Client, domain: str) -> Optional[dict]:
    """抓公司官网自己声明的图标（apple-touch-icon > icon > /favicon.ico）。

    这是覆盖率主力：live 实测 205 家必投品牌里 DuckDuckGo 只收录 65 家，而官网自有图标能拿到 166 家
    （国内公司大量不在境外 favicon 服务的收录范围内）。且是公司自证的图，不存在张冠李戴/占位污染。
    """
    for base in (f"https://{domain}", f"https://www.{domain}"):
        r = _get(client, base, timeout=_HOME_TIMEOUT)
        if r is None or r.status_code >= 400:
            continue
        try:
            html = r.text
        except Exception:  # noqa: BLE001 解码异常
            html = ""
        best = None
        for url in icon_link_urls(str(r.url), html):
            ir = _get(client, url, timeout=_HOME_TIMEOUT)
            if ir is None or ir.status_code != 200:
                continue
            cand = _candidate(ir.content, ir.headers.get("content-type"), "site")
            if cand and (best is None or cand["width"] > best["width"]):
                best = cand
        return best  # 首页打开了就以它为准，不再试其他 base（避免重复抓）
    return None


def fetch_one(client: httpx.Client, domain: str, placeholders: set) -> Optional[dict]:
    """抓一家公司的 logo，三源取最清晰者。返回 {bytes, content_type, width, source} 或 None。

    来源优先级按「清晰度」排（都过内容嗅探门）：
      1. DuckDuckGo —— live 实测无重复 md5（干净，有就是真 logo），但多为 16-32px 小图、收录率低；
      2. 公司官网自有图标 —— 覆盖率最高、常是 180px apple-touch-icon，最权威；
      3. icon.horse —— 仅在前两路都空时兜底，且必须过字母头像占位门。
    """
    cands = []
    ddg = _get(client, _DDG.format(domain=domain))
    if ddg is not None and ddg.status_code == 200:
        cand = _candidate(ddg.content, ddg.headers.get("content-type"), "duckduckgo")
        if cand:
            cands.append(cand)

    # 已有图够清晰就不用再抓官网（省请求）；没有或偏小则去官网找大图
    if not cands or max(c["width"] for c in cands) < _SMALL_WIDTH:
        try:
            site = fetch_site_icon(client, domain)
        except Exception as e:  # noqa: BLE001
            print(f"[logo] 官网图标抓取异常 {domain}: {e}", file=sys.stderr)
            site = None
        if site:
            cands.append(site)

    # 前两路都空 → icon.horse 兜底（救「域名准确但 DuckDuckGo 未收录、官网又打不开」的公司）
    if not cands:
        ih = _get(client, _ICON_HORSE.format(domain=domain))
        if (
            ih is not None
            and ih.status_code == 200
            and ih.content
            and not is_placeholder(ih.content, placeholders)
        ):
            cand = _candidate(ih.content, ih.headers.get("content-type"), "iconhorse")
            if cand:
                cands.append(cand)

    if not cands:
        return None
    return max(cands, key=lambda c: (c["width"], len(c["bytes"])))


def find_fake_logo_keys(sb, placeholders: set) -> set:
    """复检**已入库**的图，找出「假 logo」（应重抓/退回首字母兜底）。两条判据：

    1. md5 命中 icon.horse 占位指纹 —— 旧实现只取了 2 个字母的指纹，其余 34 个字母的
       灰底字母块被当成真 logo 入库（live 实测 538 张 iconhorse 图里 303 张是这种）；
    2. 同一张图跨**多个不同域名**出现 —— 真 logo 一家一张，跨域名重复必是平台/占位图。
       按域名而非公司名去重：同品牌多个名字变体（「美团」/「美团 meituan」）共用一个域名，不算重复。
    """
    try:
        rows = (
            sb.table("company_logos")
            .select("company_key,domain,logo_data")
            .eq("status", "found")
            .execute()
            .data
            or []
        )
    except Exception as e:  # noqa: BLE001
        print(f"[logo] 复检读取失败，跳过修复：{e}", file=sys.stderr)
        return set()

    by_md5: dict = {}
    for r in rows:
        data = r.get("logo_data") or ""
        if "," not in data:
            continue
        try:
            raw = base64.b64decode(data.split(",", 1)[1])
        except Exception:  # noqa: BLE001
            continue
        md5 = hashlib.md5(raw).hexdigest()
        by_md5.setdefault(md5, []).append((r["company_key"], (r.get("domain") or "").lower()))

    bad: set = set()
    for md5, entries in by_md5.items():
        distinct_domains = {d for _, d in entries if d}
        if md5 in placeholders or len(distinct_domains) > 1:
            bad.update(k for k, _ in entries)
    print(f"[logo] 复检 {len(rows)} 张已入库图 → {len(bad)} 张判定为假 logo，将重抓")
    return bad


def _page_signal_text(html: str) -> str:
    """取页面「自证身份」的文本：<title> + og:site_name + description/keywords（够核验，不必整页）。"""
    if not html:
        return ""
    bits = []
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if m:
        bits.append(re.sub(r"\s+", " ", m.group(1)).strip())
    for pat in (
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+name=["\']keywords["\'][^>]+content=["\']([^"\']+)',
    ):
        m2 = re.search(pat, html, re.I)
        if m2:
            bits.append(m2.group(1).strip())
    return " | ".join(bits)[:600]


def resolve_domain_by_slug(client: httpx.Client, company: str, source_url: str) -> Optional[str]:
    """平台托管公司（北森/moka/飞书/workday…）：用 URL 里的 slug 猜品牌域名，**页面核验通过才认**。

    核验门是防张冠李戴的唯一防线（live 实测：轻松集团 slug=qsc → qsc.cn 实为美国音响公司 QSC，被正确拒）。
    核验不过 / 域名不可达 → None，交回首字母兜底（宁缺毋滥）。
    """
    slug = platform_slug(source_url)
    if not slug:
        return None
    for domain in candidate_domains(slug):
        # 裸域名不通时再试 www.（不少企业站只在 www 生效）；DNS 不存在会快速失败，成本低
        for url in (f"https://{domain}", f"https://www.{domain}"):
            try:
                r = client.get(url, timeout=_HOME_TIMEOUT)
            except Exception:
                continue
            if r.status_code >= 400:
                continue
            try:
                text = _page_signal_text(r.text)
            except Exception:  # noqa: BLE001 解码异常等
                continue
            if page_verifies_company(company, slug, text):
                print(f"[logo] slug 核验通过：{company} → {domain}（{text[:38]}）")
                return domain
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少家公司（0=全部）")
    ap.add_argument("--force", action="store_true", help="忽略 30 天新鲜度，全部重抓")
    ap.add_argument(
        "--refetch-not-found",
        action="store_true",
        help="只对上次没抓到（status=not_found）的公司忽略新鲜度重抓（补了域名覆盖表后用）",
    )
    ap.add_argument(
        "--repair-placeholders",
        action="store_true",
        help="复检已入库的图，把占位图/跨域名重复图（假 logo）忽略新鲜度重抓一遍",
    )
    args = ap.parse_args()

    sb = get_supabase()
    sources = get_sources(sb)

    # 已有记录：新鲜度 + 已解析域名（已核验过的域名复用，重跑不必再核验一遍）+ 上次结果
    existing: dict = {}
    known_domain: dict = {}
    prev_status: dict = {}
    try:
        rows = sb.table("company_logos").select("company_key,fetched_at,domain,status").execute().data or []
        for r in rows:
            existing[r["company_key"]] = r.get("fetched_at")
            prev_status[r["company_key"]] = r.get("status")
            if r.get("domain"):
                known_domain[r["company_key"]] = r["domain"]
    except Exception as e:  # noqa: BLE001
        print(f"[logo] 读取已有记录失败（视为空）：{e}", file=sys.stderr)

    fresh_cutoff = datetime.now(timezone.utc) - timedelta(days=_FRESH_DAYS)

    # 按 company 去重（key=lower(trim)，保留第一个 source_url），存原始名供写库
    seen: dict = {}
    for row in sources:
        company = (row.get("company") or "").strip()
        if not company:
            continue
        key = company.lower()
        if key not in seen:
            seen[key] = (company, row.get("source_url") or "")

    # 必投清单的品牌短名也要抓：校招专区 / 看板按短名（如「美团」「阿里巴巴」）展示，
    # 而 sources.company 常是全称或英文名 → 短名在 company_logos 里没有行，前端只能全走首字母兜底。
    # 这些公司没有 source_url，域名只能来自 COMPANY_DOMAIN_OVERRIDES（配不到就 not_found，仍是首字母兜底）。
    must_apply_added = 0
    for companies in must_apply.by_industry().values():
        for row in companies:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in seen:
                seen[key] = (name, "")
                must_apply_added += 1
    print(f"[logo] 必投清单补入 {must_apply_added} 个品牌短名")

    processed = 0
    stats = {"found": 0, "not_found": 0, "kept": 0, "skip": 0, "err": 0, "slug_ok": 0}
    by_source: dict = {}
    with httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "job-radar-logo/1.0"}
    ) as client:
        placeholders = collect_placeholder_fingerprints(client)
        print(f"[logo] 占位指纹 {len(placeholders)} 个；待处理公司 {len(seen)} 家")

        # 忽略新鲜度、强制重抓的 key 集合（补了域名覆盖表 / 修复假 logo 时用）
        stale_keys: set = set()
        fake_keys: set = set()
        if args.refetch_not_found:
            stale_keys.update(k for k, s in prev_status.items() if s == "not_found")
        if args.repair_placeholders:
            fake_keys = find_fake_logo_keys(sb, placeholders)
            stale_keys.update(fake_keys)

        # 先按新鲜度筛出真正要抓的公司，再并发抓（近千家公司串行抓要几小时，会撞 CI 超时；
        # 每家公司是不同 host，并发不会集中压同一站点）。
        targets = []
        for key, (company, source_url) in seen.items():
            if args.limit and len(targets) >= args.limit:
                break
            if not args.force and key not in stale_keys and existing.get(key):
                try:
                    ts = datetime.fromisoformat(str(existing[key]).replace("Z", "+00:00"))
                    if ts > fresh_cutoff:
                        stats["skip"] += 1
                        continue
                except Exception:
                    pass
            targets.append((key, company, source_url))
        print(f"[logo] 需抓取 {len(targets)} 家（跳过新鲜的 {stats['skip']} 家），并发 {_WORKERS}")

        def work(item):
            """单家公司：定域名 → 抓图 → 返回待写行（异常不外抛，坏一家不拖垮整批）。"""
            key, company, source_url = item
            slug_resolved = False
            # 域名优先级：覆盖表/非平台 host > 库里已核验过的域名 > slug 猜+页面核验（平台托管公司的兜底）
            domain = domain_for_company(company, source_url, COMPANY_DOMAIN_OVERRIDES)
            if not domain:
                domain = known_domain.get(key)
                if not domain:
                    try:
                        domain = resolve_domain_by_slug(client, company, source_url)
                        slug_resolved = bool(domain)
                    except Exception as e:  # noqa: BLE001
                        print(f"[logo] slug 解析异常 {company}: {e}", file=sys.stderr)
            result, err = None, False
            if domain:
                try:
                    result = fetch_one(client, domain, placeholders)
                except Exception as e:  # noqa: BLE001
                    print(f"[logo] 抓取异常 {company}/{domain}: {e}", file=sys.stderr)
                    err = True
            return key, company, domain, result, slug_resolved, err

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            for key, company, domain, result, slug_resolved, err in pool.map(work, targets):
                processed += 1
                if slug_resolved:
                    stats["slug_ok"] += 1
                if err:
                    stats["err"] += 1
                now_iso = datetime.now(timezone.utc).isoformat()
                # ⚠️ 不变量：抓不到时**不许**把已有的真 logo 覆写成 not_found。
                # 抓取会瞬时失败（并发/超时/站点抖动），一失败就清库等于用噪音删好数据。
                # 例外是被复检判定为假 logo 的（fake_keys）——那本来就该退回首字母兜底。
                if result is None and prev_status.get(key) == "found" and key not in fake_keys:
                    stats["kept"] += 1
                    continue
                if result is None:
                    row = {
                        "company": company, "logo_data": None, "domain": domain,
                        "width": None, "source": None, "status": "not_found", "fetched_at": now_iso,
                    }
                    stats["not_found"] += 1
                else:
                    row = {
                        "company": company,
                        "logo_data": build_data_uri(result["content_type"], result["bytes"]),
                        "domain": domain, "width": result["width"], "source": result["source"],
                        "status": "found", "fetched_at": now_iso,
                    }
                    stats["found"] += 1
                    by_source[result["source"]] = by_source.get(result["source"], 0) + 1

                try:
                    sb.table("company_logos").upsert(row, on_conflict="company_key").execute()
                except Exception as e:  # noqa: BLE001
                    print(f"[logo] 写入失败 {company}: {e}", file=sys.stderr)
                    stats["err"] += 1
                if processed % 50 == 0:
                    print(f"[logo] 进度 {processed}/{len(targets)}：{stats}", flush=True)

    print(f"[logo] 完成：{stats} 来源分布={by_source}（processed={processed}）")


if __name__ == "__main__":
    main()
