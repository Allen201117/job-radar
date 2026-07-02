"""Phase 4 海外扩源探活器：对候选 Fortune 500 / 全球大厂做 live 探活，
只把「真返回美/新/远程岗 + jd_url 能 200」的公司写进 seed 迁移（禁猜 slug 入库）。

复用现有 GreenhouseAdapter / LeverAdapter（公开 token API）+ adapter 自带地区过滤。
纯函数（decide_verdict / build_source_url / emit_migration_sql）可被单测覆盖、不打网络；
main 流程做 live fetch + jd_url HTTP 探活，由编排方手动跑。

用法：
  cd crawler && python3 probe_overseas_f500.py                 # 只探活 + 打报告
  cd crawler && python3 probe_overseas_f500.py --emit 170      # 探活 + 写 170_seed_overseas_f500.sql
  cd crawler && python3 probe_overseas_f500.py --min-overseas 5 --limit 20
"""
import argparse
import json
import os
import sys
from collections import Counter

import httpx

from adapters.greenhouse import GreenhouseAdapter
from adapters.lever import LeverAdapter

_HERE = os.path.dirname(os.path.abspath(__file__))
_TARGETS = os.path.join(_HERE, "targets_overseas_f500.json")
_OVERSEAS_REGIONS = {"US", "SG", "Remote"}
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


# ----------------------- 纯函数（可单测，不打网络） -----------------------

def build_source_url(adapter: str, token: str) -> str:
    """按 adapter 拼公开 API 的 source_url，与生产 sources 里的口径一致。"""
    token = (token or "").strip()
    if adapter == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    if adapter == "lever":
        return f"https://api.lever.co/v0/postings/{token}?mode=json"
    raise ValueError(f"unsupported adapter for probe: {adapter!r}")


def decide_verdict(kept_overseas: int, jd_statuses, min_overseas: int = 5):
    """判定候选是否合格。合格 = 真有 >=min_overseas 条海外岗 且 至少 1 条 jd_url 返回 200。
    返回 (verified: bool, reason: str)。jd_statuses = 采样 jd_url 的 HTTP 状态码列表(int/None)。"""
    if kept_overseas < min_overseas:
        return False, f"too_few_overseas({kept_overseas}<{min_overseas})"
    if not any(s == 200 for s in (jd_statuses or [])):
        # 全是 403/其它 = jd_url 反爬或失效，过不了质量门
        codes = ",".join(str(s) for s in (jd_statuses or [])) or "none"
        return False, f"jd_url_unreachable({codes})"
    return True, "ok"


def emit_migration_sql(verified_rows, prefix: str) -> str:
    """把 verified 候选生成幂等 seed 迁移 SQL。每条 INSERT 带 regions + where not exists 防重。
    verified_rows = [{company, adapter, token, url, kept_overseas}]。"""
    lines = [
        f"-- {prefix}_seed_overseas_f500.sql — Phase 4 定向补 Fortune 500 / 全球大厂海外源",
        "-- 全部经 probe_overseas_f500.py live 探活确认：真返回美/新/远程岗 + jd_url 200（禁猜 slug 入库）。",
        "-- 幂等：按 source_url 防重；regions 直接开 {CN,US,SG,Remote}。",
        "",
    ]
    for r in verified_rows:
        url = r["url"].replace("'", "''")
        company = r["company"].replace("'", "''")
        note = f"{r['company']}（{r['adapter']}，Phase4 海外扩源，探活 {r['kept_overseas']} 海外岗）".replace("'", "''")
        lines.append(
            "insert into sources (company, source_url, source_type, adapter_name, crawl_method, regions, notes)\n"
            f"select '{company}', '{url}', 'official', '{r['adapter']}', 'http', "
            "'{CN,US,SG,Remote}'::text[], "
            f"'{note}'\n"
            f"where not exists (select 1 from sources where source_url = '{url}');\n"
        )
    return "\n".join(lines)


# ----------------------- live 探活（打网络，手动跑） -----------------------

def _check_jd(url: str) -> int:
    """HTTP 探 jd_url，返回状态码；异常返回 None。带真实浏览器 UA、跟随跳转。"""
    try:
        resp = httpx.get(
            url, headers={"User-Agent": _BROWSER_UA}, timeout=20.0, follow_redirects=True
        )
        return resp.status_code
    except Exception:
        return None


def _adapter_for(adapter: str):
    if adapter == "greenhouse":
        return GreenhouseAdapter()
    if adapter == "lever":
        return LeverAdapter()
    raise ValueError(f"unsupported adapter: {adapter!r}")


def probe_one(cand: dict, min_overseas: int):
    """live 探一个候选，返回结果 dict。"""
    adapter_name = cand["adapter"]
    token = cand["token"]
    url = build_source_url(adapter_name, token)
    out = {
        "company": cand["company"], "adapter": adapter_name, "token": token, "url": url,
        "raw": 0, "kept_overseas": 0, "jd_statuses": [], "top_locs": [],
        "verified": False, "reason": "",
    }
    ad = _adapter_for(adapter_name)
    try:
        html = ad.fetch(url)
    except Exception as e:
        out["reason"] = f"fetch_failed:{type(e).__name__}"
        return out
    try:
        raw = json.loads(html)
        out["raw"] = len(raw.get("jobs", []) if isinstance(raw, dict) else raw)
    except Exception:
        out["raw"] = 0
    ad.regions = _OVERSEAS_REGIONS
    jobs = ad.parse(html)
    out["kept_overseas"] = len(jobs)
    out["top_locs"] = Counter((j.location or "?") for j in jobs).most_common(4)
    # 采样最多 3 条 jd_url 探活
    for j in jobs[:3]:
        out["jd_statuses"].append(_check_jd(j.jd_url))
    out["verified"], out["reason"] = decide_verdict(
        out["kept_overseas"], out["jd_statuses"], min_overseas
    )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit", metavar="PREFIX", default=None,
                    help="写 <PREFIX>_seed_overseas_f500.sql（如 170）")
    ap.add_argument("--min-overseas", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="只探前 N 个候选（调试）")
    args = ap.parse_args()

    with open(_TARGETS, encoding="utf-8") as f:
        cands = json.load(f)
    if args.limit:
        cands = cands[: args.limit]

    verified_rows = []
    print(f"探活 {len(cands)} 个候选（min_overseas={args.min_overseas}）...\n")
    for c in cands:
        r = probe_one(c, args.min_overseas)
        tag = "✅ VERIFIED" if r["verified"] else "✗ rejected"
        jd = ",".join(str(s) for s in r["jd_statuses"]) or "-"
        locs = " ".join(f"{loc}:{n}" for loc, n in r["top_locs"][:3])
        print(f"{tag}  {r['company']:<26} {r['adapter']:<10} {r['token']:<20} "
              f"raw={r['raw']:<4} overseas={r['kept_overseas']:<4} jd=[{jd}]  {r['reason']}  {locs}")
        if r["verified"]:
            verified_rows.append(r)

    print(f"\n合格 {len(verified_rows)} / {len(cands)}。")
    if args.emit and verified_rows:
        path = os.path.join(_HERE, "..", "supabase", "migrations",
                            f"{args.emit}_seed_overseas_f500.sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(emit_migration_sql(verified_rows, args.emit))
        print(f"已写 {os.path.normpath(path)}（{len(verified_rows)} 条 verified 源）")


if __name__ == "__main__":
    main()
