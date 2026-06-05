"""
扩源探活器 —— 批量 live 探活候选招聘源，只把**真返回岗位**的源写进迁移文件。

目的：让「全量扩源」既快又合规。遵守 CLAUDE.md 核心原则 #3「加源必须 live 探活，禁止猜 slug 入库」：
本脚本里的 CANDIDATES 只是**待探活候选**，不是已入库源；探活通过（解析出 ≥1 条过质量门的岗位）的才会
被 --emit 写进 supabase/migrations 的 INSERT。探活不过的直接丢弃。

用法（需在用户本机，有网络；.env.local 非必须，本脚本只读公开页）：
  cd crawler
  python3 probe.py                       # 只探 httpx 类（greenhouse/lever），打印结果
  python3 probe.py --all                 # 连 playwright 类（moka/beisen/company_spa）一起探（需装 playwright）
  python3 probe.py --emit 025            # 探活通过的写进 ../supabase/migrations/025_seed_probed_sources.sql
                                         # （023/024 已被上市维度占用，新前缀从 025 起递增）
  python3 probe.py --candidates my.json  # 用自定义候选清单（JSON 数组，字段同 CANDIDATES）

候选 JSON 字段：{company, adapter, url, industry?}
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import normalizer  # noqa: E402
from run import ADAPTERS  # noqa: E402

# httpx 类（无需浏览器，探活便宜）
_HTTPX_ADAPTERS = {"greenhouse", "lever", "apple", "apple_cn", "baidu", "jd", "siemens", "haier"}

# 待探活候选（跨行业，刻意分散覆盖面）。greenhouse/lever 用公开 boards-api，探活只需 httpx。
# 注意：这里全部是**候选**，live 探活通过才入库。slug 探不到的会被自动丢弃，不会污染生产。
CANDIDATES = [
    # —— 消费 / 零售 / 餐饮 ——
    {"company": "Nike", "adapter": "greenhouse", "industry": "消费·运动",
     "url": "https://boards-api.greenhouse.io/v1/boards/nike/jobs?content=true"},
    {"company": "lululemon", "adapter": "greenhouse", "industry": "消费·运动",
     "url": "https://boards-api.greenhouse.io/v1/boards/lululemon/jobs?content=true"},
    # —— 互联网 / SaaS ——
    {"company": "Airbnb", "adapter": "greenhouse", "industry": "互联网·旅行",
     "url": "https://boards-api.greenhouse.io/v1/boards/airbnb/jobs?content=true"},
    {"company": "Stripe", "adapter": "greenhouse", "industry": "金融科技",
     "url": "https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"},
    {"company": "Databricks", "adapter": "greenhouse", "industry": "数据·AI",
     "url": "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true"},
    {"company": "Canva", "adapter": "lever", "industry": "设计·SaaS",
     "url": "https://api.lever.co/v0/postings/canva?mode=json"},
    # —— 半导体 / 硬件 ——
    {"company": "NVIDIA", "adapter": "greenhouse", "industry": "半导体·AI",
     "url": "https://boards-api.greenhouse.io/v1/boards/nvidia/jobs?content=true"},
    {"company": "AMD", "adapter": "greenhouse", "industry": "半导体",
     "url": "https://boards-api.greenhouse.io/v1/boards/amd/jobs?content=true"},
    # —— 医药 / 生物 ——
    {"company": "BeiGene 百济神州", "adapter": "greenhouse", "industry": "生物医药",
     "url": "https://boards-api.greenhouse.io/v1/boards/beigene/jobs?content=true"},
    # —— 金融 / 量化 ——
    {"company": "Citadel", "adapter": "greenhouse", "industry": "对冲基金·量化",
     "url": "https://boards-api.greenhouse.io/v1/boards/citadel/jobs?content=true"},
    {"company": "IMC Trading", "adapter": "greenhouse", "industry": "量化",
     "url": "https://boards-api.greenhouse.io/v1/boards/imc/jobs?content=true"},
    # —— 游戏 ——
    {"company": "Riot Games", "adapter": "greenhouse", "industry": "游戏",
     "url": "https://boards-api.greenhouse.io/v1/boards/riotgames/jobs?content=true"},
    # —— 本土 Moka / 北森 候选（playwright，--all 才探）——
    # 这些是示例占位：填上你确认存在的某公司 Moka/北森公开招聘页地址即可被探活。
    # {"company": "某公司", "adapter": "moka", "industry": "...",
    #  "url": "https://xxx.mokahr.com/social-recruitment/campus/xxx"},
    # {"company": "某集团", "adapter": "beisen", "industry": "...",
    #  "url": "https://xxx.zhiye.com/..."},
]


def probe_one(cand: dict):
    adapter = ADAPTERS.get(cand["adapter"])
    if adapter is None:
        return {"ok": False, "valid": 0, "reason": f"unknown adapter {cand['adapter']}"}
    try:
        html = adapter.fetch(cand["url"])
        raw_jobs = adapter.parse(html)
    except Exception as e:  # 探活失败（网络/反爬/结构不符）→ 丢弃，不入库
        return {"ok": False, "valid": 0, "reason": f"{type(e).__name__}: {e}"}

    valid = 0
    sample = None
    for raw in raw_jobs:
        if not raw.company:
            raw.company = cand["company"]
        is_valid, _ = normalizer.validate_job_quality(raw, cand["url"])
        if is_valid:
            valid += 1
            if sample is None:
                sample = raw.jd_url
    return {"ok": valid > 0, "valid": valid, "parsed": len(raw_jobs), "sample": sample}


def emit_sql(prefix: str, passed: list):
    lines = [
        f"-- {prefix} — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）",
        "-- Idempotent: guarded by source_url.\n",
    ]
    for c in passed:
        notes = f"{c['company']}（{c.get('industry', '')}，probe live 探活 {c['_valid']} 岗）"
        url = c["url"].replace("'", "''")
        lines.append(
            "insert into sources (company, source_url, source_type, adapter_name, crawl_method, notes)\n"
            f"select '{c['company']}', '{url}', 'official', '{c['adapter']}', "
            f"'{'http' if c['adapter'] in _HTTPX_ADAPTERS else 'playwright'}', '{notes}'\n"
            f"where not exists (select 1 from sources where source_url = '{url}');\n"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="扩源探活器")
    ap.add_argument("--all", action="store_true", help="连 playwright 类一起探（需装 playwright）")
    ap.add_argument("--emit", type=str, default=None, help="探活通过的写迁移，传前缀如 023")
    ap.add_argument("--candidates", type=str, default=None, help="自定义候选 JSON 文件")
    args = ap.parse_args()

    cands = CANDIDATES
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as f:
            cands = json.load(f)

    if not args.all:
        cands = [c for c in cands if c["adapter"] in _HTTPX_ADAPTERS]

    passed = []
    print(f"[probe] 探活 {len(cands)} 个候选源...\n")
    for c in cands:
        r = probe_one(c)
        flag = "✓" if r["ok"] else "✗"
        detail = (f"valid={r['valid']} parsed={r.get('parsed', '-')} {r.get('sample', '')}"
                  if r["ok"] else r.get("reason", ""))
        print(f"  {flag} [{c['adapter']:11}] {c['company']:22} {detail}")
        if r["ok"]:
            c = {**c, "_valid": r["valid"]}
            passed.append(c)

    print(f"\n[probe] 通过 {len(passed)}/{len(cands)}。")
    if args.emit and passed:
        path = os.path.join(os.path.dirname(__file__), "..", "supabase", "migrations",
                            f"{args.emit}_seed_probed_sources.sql")
        with open(path, "w", encoding="utf-8") as f:
            f.write(emit_sql(args.emit, passed))
        print(f"[probe] 已写 {os.path.relpath(path)}（{len(passed)} 源）。push 后自动迁移生效。")
    elif args.emit:
        print("[probe] 无通过源，未写迁移。")


if __name__ == "__main__":
    main()
