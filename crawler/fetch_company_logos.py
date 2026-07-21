"""抓取企业 logo（favicon）→ base64 存 company_logos。海外 CI 跑（能直连境外 favicon 服务）。

来源与质量门（见 CLAUDE.md「企业 logo」）：
- DuckDuckGo（icons.duckduckgo.com）是「有没有 logo」的权威：404→not_found（不存图），200→有。
- icon.horse 仅作 DuckDuckGo 图偏小时的高清升级，且必须过「占位污染门」（它对任何域名都返回占位图）。
- 存 data URI（base64）：国内直连境外 favicon 服务会被墙，必须抓下来跟着我们域名走。

用法：python3 fetch_company_logos.py [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from db import get_sources, get_supabase
from logo_util import (
    COMPANY_DOMAIN_OVERRIDES,
    build_data_uri,
    domain_for_company,
    image_width,
    is_placeholder,
)

_TIMEOUT = 15.0
_FRESH_DAYS = 30
_SMALL_WIDTH = 48          # DuckDuckGo 图窄于此 → 试 icon.horse 升级
_MAX_BYTES = 200_000       # favicon 不该更大；超过视为异常，不入库（首字母兜底）
_DDG = "https://icons.duckduckgo.com/ip3/{domain}.ico"
_ICON_HORSE = "https://icon.horse/icon/{domain}"
# icon.horse 占位指纹用的必然不存在域名
_FAKE_DOMAINS = ["zzz-not-a-real-company-9x7q.com", "no-such-brand-4k2p-domain.com"]


def _get(client: httpx.Client, url: str) -> Optional[httpx.Response]:
    for attempt in range(2):
        try:
            return client.get(url)
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                print(f"[logo] 请求失败 {url}: {e}", file=sys.stderr)
                return None
    return None


def collect_placeholder_fingerprints(client: httpx.Client) -> set:
    """抓几个必然不存在的域名的 icon.horse 图，其 md5 即占位指纹（用于后续过滤）。"""
    prints = set()
    for d in _FAKE_DOMAINS:
        r = _get(client, _ICON_HORSE.format(domain=d))
        if r is not None and r.status_code == 200 and r.content:
            prints.add(hashlib.md5(r.content).hexdigest())
    return prints


def fetch_one(client: httpx.Client, domain: str, placeholders: set) -> Optional[dict]:
    """抓一家公司的 logo。返回 {bytes, content_type, width, source} 或 None（DuckDuckGo 404 = 这家没有）。"""
    ddg = _get(client, _DDG.format(domain=domain))
    if ddg is None or ddg.status_code == 404 or ddg.status_code != 200 or not ddg.content:
        return None
    best = ddg.content
    best_ct = ddg.headers.get("content-type")
    source = "duckduckgo"
    width = image_width(best)

    # 偏小 → 试 icon.horse 高清升级（过占位门 + 取更清晰/更大者）
    if width is None or width < _SMALL_WIDTH:
        ih = _get(client, _ICON_HORSE.format(domain=domain))
        if (
            ih is not None
            and ih.status_code == 200
            and ih.content
            and not is_placeholder(ih.content, placeholders)
        ):
            ih_w = image_width(ih.content)
            if (ih_w or 0) > (width or 0) or len(ih.content) > len(best):
                best, best_ct, source, width = ih.content, ih.headers.get("content-type"), "iconhorse", ih_w

    if len(best) > _MAX_BYTES:
        print(f"[logo] {domain} 图过大({len(best)}B)，跳过", file=sys.stderr)
        return None
    return {"bytes": best, "content_type": best_ct, "width": width, "source": source}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="最多处理多少家公司（0=全部）")
    ap.add_argument("--force", action="store_true", help="忽略 30 天新鲜度，全部重抓")
    args = ap.parse_args()

    sb = get_supabase()
    sources = get_sources(sb)

    # 已有记录的新鲜度
    existing: dict = {}
    try:
        rows = sb.table("company_logos").select("company_key,fetched_at").execute().data or []
        for r in rows:
            existing[r["company_key"]] = r.get("fetched_at")
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

    processed = 0
    stats = {"found": 0, "not_found": 0, "skip": 0, "err": 0}
    with httpx.Client(
        timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": "job-radar-logo/1.0"}
    ) as client:
        placeholders = collect_placeholder_fingerprints(client)
        print(f"[logo] 占位指纹 {len(placeholders)} 个；待处理公司 {len(seen)} 家")

        for key, (company, source_url) in seen.items():
            if args.limit and processed >= args.limit:
                break
            # 新鲜度跳过
            if not args.force and existing.get(key):
                try:
                    ts = datetime.fromisoformat(str(existing[key]).replace("Z", "+00:00"))
                    if ts > fresh_cutoff:
                        stats["skip"] += 1
                        continue
                except Exception:
                    pass
            processed += 1

            now_iso = datetime.now(timezone.utc).isoformat()
            domain = domain_for_company(company, source_url, COMPANY_DOMAIN_OVERRIDES)
            result = None
            if domain:
                try:
                    result = fetch_one(client, domain, placeholders)
                except Exception as e:  # noqa: BLE001
                    print(f"[logo] 抓取异常 {company}/{domain}: {e}", file=sys.stderr)
                    stats["err"] += 1

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

            try:
                sb.table("company_logos").upsert(row, on_conflict="company_key").execute()
            except Exception as e:  # noqa: BLE001
                print(f"[logo] 写入失败 {company}: {e}", file=sys.stderr)
                stats["err"] += 1

    print(f"[logo] 完成：{stats}（processed={processed}）")


if __name__ == "__main__":
    main()
