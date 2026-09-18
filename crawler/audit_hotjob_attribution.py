"""复核 wecruit（hotjob）存量源的公司归属：sources.company 与租户自报的 suite/config.companyName 对不上就报出来。

治的病：接 wecruit 源时公司名是人/清单给的，suiteKey 是探活猜的，探活只证明「这个租户真出岗」，
不证明「这个租户就是我们猜的那家公司」。已经两次张冠李戴：
  · 248：jd.hotjob.cn 记成京东，实为精雕科技（74 岗）
  · 274：wecruit SU612f55… 记成领益智造，实为特变电工（1,903 岗，挂错三个月无人发现）
新接源的门在 discover_domestic._hotjob_channel / gap_funnel 的 identity 核验里已经有了；**这个脚本查的是存量**——
每个 enabled 的 wecruit 源问一次租户自己的 `suite/config`（companyName 是租户后台填的，与探活无关），
两个方向任一方向核心 token 能对上就算通过（「新疆特变电工集团」↔「特变电工股份有限公司」靠反向的「特变电工」对上）。

只读、没有 --apply：对不上的源要人看过 suite/config 原文再决定改名（走 sources 迁移 + rename-job-company.yml），
因为「对不上」也可能是品牌名 vs 法人名（如「领益智造」vs「广东领益智造股份有限公司」这种是对得上的，
但「TME」vs「腾讯音乐娱乐」这种拉丁品牌名就对不上）。接口失败一律记 unknown、不判错。

用法：
    python3 crawler/audit_hotjob_attribution.py            # 全部 enabled wecruit 源
    python3 crawler/audit_hotjob_attribution.py --limit 20
"""
import argparse
import os
import re
import sys
from urllib.parse import urlparse

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover_domestic import _core_tokens  # noqa: E402

_CONFIG_API = "/wecruit/suite/config/"
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_CHANNEL_SUFFIX = re.compile(r"(校招|社招|实习|校园招聘|社会招聘|实习生)$")
_NON_CJK = re.compile(r"[^一-鿿]+")


def cjk_name(company: str) -> str:
    """sources.company → 只留中文、去掉渠道后缀：「领益智造 Lingyi 实习」→「领益智造」。"""
    cn = _NON_CJK.sub("", company or "")
    prev = None
    while prev != cn:
        prev, cn = cn, _CHANNEL_SUFFIX.sub("", cn)
    return cn


def names_agree(source_company: str, tenant_company: str) -> bool:
    """双向核心 token 包含：任一方向对上即通过。两边任一为空 → False（调用方按 unknown 处理）。"""
    a, b = cjk_name(source_company), (tenant_company or "").strip()
    if not a or not b:
        return False
    return any(t in b for t in _core_tokens(a)) or any(t in a for t in _core_tokens(b))


def tenant_company_name(source_url: str, client: httpx.Client):
    """POST suite/config，返回 (companyName, error)。失败返回 (None, 原因)。"""
    parsed = urlparse(source_url)
    parts = [p for p in (parsed.path or "").split("/") if p]
    if not parts:
        return None, "no suite key"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        r = client.post(f"{origin}{_CONFIG_API}{parts[0]}",
                        headers={"Referer": source_url, "Origin": origin})
        data = (r.json() or {}).get("data") or {}
        name = str(data.get("companyName") or "").strip()
        return (name or None), (None if name else "no companyName in data")
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def load_sources(sb, limit=None):
    """enabled 的 wecruit 源（/pb/ 形态）；PostgREST 默认 1000 行截断，这里分页取全。"""
    rows, page, size = [], 0, 1000
    while True:
        res = (sb.table("sources").select("id,company,source_url,adapter_name")
               .eq("adapter_name", "hotjob").eq("enabled", True)
               .like("source_url", "%/pb/%")
               .order("source_url").range(page * size, page * size + size - 1).execute())
        batch = res.data or []
        rows.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return rows[:limit] if limit else rows


def audit(rows, client):
    """返回 (mismatches, unknowns, ok_count)。同一租户的多条源只问一次接口。"""
    cache = {}
    mismatches, unknowns, ok = [], [], 0
    for row in rows:
        url = row["source_url"]
        key = urlparse(url).netloc + "/" + ([p for p in urlparse(url).path.split("/") if p] or [""])[0]
        if key not in cache:
            cache[key] = tenant_company_name(url, client)
        tenant, err = cache[key]
        if tenant is None:
            unknowns.append((row["company"], url, err))
        elif names_agree(row["company"], tenant):
            ok += 1
        else:
            mismatches.append((row["company"], url, tenant))
    return mismatches, unknowns, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    from db import get_supabase  # noqa: E402  延迟导入：单测不需要 Supabase 环境
    rows = load_sources(get_supabase(), args.limit)
    with httpx.Client(timeout=20, follow_redirects=True,
                      headers={"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}) as client:
        mismatches, unknowns, ok = audit(rows, client)
    print(f"[audit-hotjob] sources={len(rows)} ok={ok} mismatch={len(mismatches)} unknown={len(unknowns)}")
    for company, url, tenant in mismatches:
        print(f"::warning::归属对不上: sources.company='{company}' 租户自报='{tenant}' {url}")
    for company, url, err in unknowns:
        print(f"  unknown: '{company}' {url} ({err})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
