"""
扩源探活器 —— 批量 live 探活候选招聘源，只把**真返回岗位**的源写进迁移文件。

目的：让「全量扩源」既快又合规。遵守 CLAUDE.md 核心原则 #3「加源必须 live 探活，禁止猜 slug 入库」：
本脚本里的 CANDIDATES 只是**待探活候选**，不是已入库源；探活通过（解析出 ≥1 条过质量门的岗位）的才会
被 --emit 写进 supabase/migrations 的 INSERT。探活不过的直接丢弃。

用法（需在用户本机，有网络；.env.local 非必须，本脚本只读公开页）：
  cd crawler
  python3 probe.py                       # 只探 httpx 类（greenhouse/lever），打印结果
  python3 probe.py --all                 # 连 playwright 类（moka/beisen/company_spa）一起探（需装 playwright）
  python3 probe.py --emit 026            # 探活通过的写进 ../supabase/migrations/026_seed_probed_sources.sql
                                         # （023/024/025 已被上市维度占用，新前缀从 026 起递增）
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

# 待探活候选（跨行业，刻意分散覆盖面，对标「外企100强 + 跨行业龙头」）。
# greenhouse/lever 用公开 boards-api，探活只需 httpx。
# 注意：这里全部是**候选**，live 探活通过才入库。slug 探不到 / 结构不符的会被自动丢弃，不污染生产。
# 用 `python3 probe.py --emit 026` 在你本机一次性 live 验证 + 生成迁移，只有真返回岗位的才入库。
def _gh(slug):
    return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


def _lever(slug):
    return f"https://api.lever.co/v0/postings/{slug}?mode=json"


# (company, slug, adapter, industry)，按行业分散，对标外企/跨国龙头各行各业覆盖。
_FOREIGN = [
    # —— 消费 / 零售 / 运动 / 餐饮 ——
    ("Nike", "nike", "greenhouse", "消费·运动"),
    ("lululemon", "lululemon", "greenhouse", "消费·运动"),
    ("Sweetgreen", "sweetgreen", "greenhouse", "消费·餐饮"),
    ("Warby Parker", "warbyparker", "greenhouse", "消费·零售"),
    ("Faire", "faire", "greenhouse", "消费·批发"),
    # —— 互联网 / 平台 / 旅行 ——
    ("Airbnb", "airbnb", "greenhouse", "互联网·旅行"),
    ("DoorDash", "doordash", "greenhouse", "互联网·本地"),
    ("Instacart", "instacart", "greenhouse", "互联网·零售"),
    ("Reddit", "reddit", "greenhouse", "互联网·社区"),
    ("Pinterest", "pinterest", "greenhouse", "互联网·社区"),
    ("Lyft", "lyft", "greenhouse", "互联网·出行"),
    # —— 企业 SaaS / 开发者工具 ——
    ("Stripe", "stripe", "greenhouse", "金融科技"),
    ("Databricks", "databricks", "greenhouse", "数据·AI"),
    ("Snowflake", "snowflake", "greenhouse", "数据"),
    ("HashiCorp", "hashicorp", "greenhouse", "云基础设施"),
    ("GitLab", "gitlab", "greenhouse", "开发者工具"),
    ("Cloudflare", "cloudflare", "greenhouse", "云·安全"),
    ("Datadog", "datadog", "greenhouse", "可观测性"),
    ("Twilio", "twilio", "greenhouse", "通信云"),
    ("Asana", "asana", "greenhouse", "协作 SaaS"),
    ("Dropbox", "dropbox", "greenhouse", "云存储"),
    ("Samsara", "samsara", "greenhouse", "物联网 SaaS"),
    ("Retool", "retool", "greenhouse", "开发者工具"),
    ("Benchling", "benchling", "greenhouse", "生物科技 SaaS"),
    # —— AI ——
    ("OpenAI", "openai", "greenhouse", "AI"),
    ("Anthropic", "anthropic", "greenhouse", "AI"),
    ("Scale AI", "scaleai", "greenhouse", "AI·数据标注"),
    # —— 金融科技 / 加密 / 量化 ——
    ("Coinbase", "coinbase", "greenhouse", "加密金融"),
    ("Robinhood", "robinhood", "greenhouse", "金融科技"),
    ("Brex", "brex", "greenhouse", "金融科技"),
    ("Plaid", "plaid", "greenhouse", "金融科技"),
    ("Affirm", "affirm", "greenhouse", "金融科技"),
    ("Ramp", "ramp", "greenhouse", "金融科技"),
    ("Chime", "chime", "greenhouse", "金融科技"),
    ("Citadel", "citadel", "greenhouse", "对冲基金·量化"),
    ("IMC Trading", "imc", "greenhouse", "量化"),
    # —— 半导体 / 硬件 ——
    ("NVIDIA", "nvidia", "greenhouse", "半导体·AI"),
    ("AMD", "amd", "greenhouse", "半导体"),
    # —— 医药 / 生物 ——
    ("BeiGene 百济神州", "beigene", "greenhouse", "生物医药"),
    # —— 游戏 / 娱乐 ——
    ("Riot Games", "riotgames", "greenhouse", "游戏"),
    ("Discord", "discord", "greenhouse", "社交·游戏"),
    # —— lever 系 ——
    ("Canva", "canva", "lever", "设计·SaaS"),
    ("Netflix", "netflix", "lever", "流媒体"),
]

CANDIDATES = [
    {"company": c, "adapter": a, "industry": ind, "url": (_gh(s) if a == "greenhouse" else _lever(s))}
    for (c, s, a, ind) in _FOREIGN
]

# —— 本土 Moka / 北森 / 企业官网 SPA 候选（playwright，--all 才探）——
# 中国 500 强多数用自建 SPA 或 moka(mokahr.com) / 北森(zhiye.com)；子域因公司而异，不可猜测（猜错=乱爬）。
# 填上你**确认存在**的公开招聘页地址（浏览器能打开、能看到岗位列表的那个 URL）即可被 live 探活后入库。
# 例：
#   {"company": "某集团", "adapter": "moka", "industry": "制造",
#    "url": "https://xxx.mokahr.com/social-recruitment/campus/xxx"},
#   {"company": "某银行", "adapter": "beisen", "industry": "金融",
#    "url": "https://xxx.zhiye.com/..."},
#   {"company": "某公司", "adapter": "company_spa", "industry": "...",
#    "url": "https://careers.example.com/..."},
_DOMESTIC = [
    # 在此追加已 live 验证可打开的本土招聘页（adapter ∈ moka/beisen/company_spa）。
]
CANDIDATES += _DOMESTIC


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
