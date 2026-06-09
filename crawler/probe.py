"""
扩源探活器 —— 批量 live 探活候选招聘源，只把**真返回岗位**的源写进迁移文件。

目的：让「全量扩源」既快又合规。遵守 CLAUDE.md 核心原则 #3「加源必须 live 探活，禁止猜 slug 入库」：
本脚本里的 CANDIDATES 只是**待探活候选**，不是已入库源；探活通过（解析出 ≥1 条过质量门的岗位）的才会
被 --emit 写进 supabase/migrations 的 INSERT。探活不过的直接丢弃。

用法（需在用户本机，有网络；.env.local 非必须，本脚本只读公开页）：
  cd crawler
  python3 probe.py                       # 只探内置精选 httpx 候选（greenhouse/lever/ashby/smartrecruiters）
  python3 probe.py --discover            # 发现模式：对内置跨行业公司名 × ATS × slug 变体自动猜 + live 验证（外企扩源主力）
  python3 probe.py --discover --emit 026 # 发现并把通过的写进 ../supabase/migrations/026_seed_probed_sources.sql
                                         # （023/024/025 已被上市维度占用，新前缀从 026 起递增）
  python3 probe.py --all                 # 连 playwright 类（moka/beisen/company_spa）一起探（需装 playwright）
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
_HTTPX_ADAPTERS = {
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "eightfold", "oracle",
    "amazon",  # 外企自建：Amazon.jobs search.json
    "apple", "apple_cn", "baidu", "jd", "siemens", "haier",
    "hotjob",  # 本土 wecruit：直连 listPosition 接口，无浏览器（详见 adapters/hotjob.py）
}

# 通用 ATS 的 URL 模板：给定 slug 即可拼出公开 JSON 接口地址。
# discover 模式据此对每个公司名 × 每个平台 × 若干 slug 变体生成候选，再 live 验证、只留真返回岗位的。
_ATS_URL = {
    "greenhouse": lambda s: f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs?content=true",
    "lever": lambda s: f"https://api.lever.co/v0/postings/{s}?mode=json",
    "ashby": lambda s: f"https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true",
    "smartrecruiters": lambda s: f"https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=100",
}

# 待探活候选（跨行业，刻意分散覆盖面，对标「外企100强 + 跨行业龙头」）。
# greenhouse/lever 用公开 boards-api，探活只需 httpx。
# 注意：这里全部是**候选**，live 探活通过才入库。slug 探不到 / 结构不符的会被自动丢弃，不污染生产。
# 用 `python3 probe.py --emit 026` 在你本机一次性 live 验证 + 生成迁移，只有真返回岗位的才入库。
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
    # —— SmartRecruiters 系（外企100强主力：大量在华跨国制造/消费/金融用此 ATS）——
    ("Bosch 博世", "BoschGroup", "smartrecruiters", "汽车·工业"),
    ("Visa", "Visa", "smartrecruiters", "金融·支付"),
    ("Ubisoft 育碧", "Ubisoft", "smartrecruiters", "游戏"),
    ("Schneider Electric 施耐德", "SchneiderElectric", "smartrecruiters", "能源·工业"),
    ("LVMH", "LVMH", "smartrecruiters", "奢侈品·消费"),
    ("Equinix", "Equinix", "smartrecruiters", "数据中心"),
    ("Avery Dennison", "AveryDennison", "smartrecruiters", "材料·制造"),
    ("Skechers", "skechers", "smartrecruiters", "消费·运动"),
    ("Biogen", "Biogen", "smartrecruiters", "生物医药"),
    ("McDonald's 麦当劳", "McDonalds", "smartrecruiters", "消费·餐饮"),
    # —— Ashby 系 ——
    ("Notion", "notion", "ashby", "协作 SaaS"),
    ("Linear", "linear", "ashby", "开发者工具"),
    ("Ramp", "ramp", "ashby", "金融科技"),
    ("Vanta", "vanta", "ashby", "安全合规"),
]

# 通用 URL 拼装：ATS 平台 → slug → 公开接口地址；非 ATS（apple/baidu…）保留原 url。
CANDIDATES = [
    {"company": c, "adapter": a, "industry": ind, "url": _ATS_URL[a](s)}
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

# —— Workday 系（外企100强主力；CXS 端点 = {host}/wday/cxs/{tenant}/{site}/jobs）——
# host 的 wd{N} 与 site 名不可猜，均来自公开检索确认；adapter 用 location facet 服务端过滤在华。
# 已 live 验证在华岗位 > 0（probe china-gate 会再校验一次）。
_WORKDAY = [
    ("NVIDIA", "半导体·AI", "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/jobs"),
    ("Pfizer 辉瑞", "医药", "https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs"),
    ("Citi 花旗", "金融", "https://citi.wd5.myworkdayjobs.com/wday/cxs/citi/2/jobs"),
    ("MSD 默沙东", "医药", "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs"),
    ("Mastercard 万事达", "金融·支付", "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs"),
]
CANDIDATES += [
    {"company": c, "adapter": "workday", "industry": ind, "url": url} for (c, ind, url) in _WORKDAY
]


# ───────────────────────── discover：按公司名自动找 ATS + slug ─────────────────────────
# 「最高效扩源」引擎：给一串公司名，机器对每个名 × 每个单 host 的 ATS 平台 × 若干 slug 变体
# 生成候选 URL，再 live 验证，只把**真返回岗位**的写入迁移。slug 是机器猜的，但探不到就丢弃，
# 不会污染生产（符合 CLAUDE.md「禁止猜 slug 入库」——入库的前提永远是 live 验证通过）。
# 注意：仅适用于「单 host + slug」型 ATS（greenhouse/lever/ashby/smartrecruiters）。
# 本土 moka/beisen 是「每公司独立子域」，host 无法由公司名稳定推断，仍需在 _DOMESTIC 填真实 URL。
_DISCOVER_PLATFORMS = ["greenhouse", "lever", "ashby", "smartrecruiters"]

# eightfold 自动猜：{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}
# tenant=compact slug；domain 默认 {slug}.com，少数公司域名特殊用 _EF_DOMAINS 覆盖。
_EF_DOMAINS = {
    "stmicroelectronics": "stmicroelectronics.com", "hsbc": "hsbc.com",
    "schneiderelectric": "se.com", "procterandgamble": "pg.com", "loreal": "loreal.com",
    "jpmorgan": "jpmorganchase.com", "texasinstruments": "ti.com",
}


def _eightfold_url(tenant: str, domain: str) -> str:
    return f"https://{tenant}.eightfold.ai/api/apply/v2/jobs?domain={domain}"


def slugify(name: str):
    """公司名 → 若干 slug 变体（紧凑 / 连字符 / 去常见后缀）。仅取拉丁部分（slug 不含中文）。"""
    import re

    latin = re.sub(r"[^a-zA-Z0-9 &-]+", " ", name)        # 去中文与符号，留拉丁+空格+&-
    latin = latin.replace("&", " and ").strip().lower()
    if not latin:
        return []
    words = [w for w in re.split(r"[^a-z0-9]+", latin) if w]
    # 去掉公司后缀噪声，让 slug 更可能命中
    stop = {"inc", "ltd", "co", "corp", "corporation", "group", "the", "limited", "plc", "llc"}
    core = [w for w in words if w not in stop] or words
    compact = "".join(core)
    hyphen = "-".join(core)
    # CamelCase 紧凑变体：SmartRecruiters 的 identifier 多为大小写敏感（Visa/Ubisoft/SchneiderElectric…）
    camel = "".join(w.capitalize() for w in core)
    variants = []
    for v in (compact, hyphen, "".join(words), camel):
        if v and v not in variants:
            variants.append(v)
    return variants


# 跨行业「外企100强 / 跨国龙头」发现种子（仅名字；slug 由机器猜 + live 验证）。
# 刻意覆盖各行业，避免只剩互联网。能否入库由 live 探活决定，列在这里零风险。
_DISCOVER_NAMES = [
    # 汽车 / 工业 / 能源
    "Bosch", "Siemens", "Schneider Electric", "ABB", "Honeywell", "Caterpillar",
    "Cummins", "Emerson", "Continental", "Valeo", "Tesla",
    # 消费 / 零售 / 餐饮 / 奢侈
    "Nike", "Adidas", "lululemon", "Starbucks", "McDonald's", "Nestle", "Unilever",
    "Procter & Gamble", "L'Oreal", "LVMH", "Estee Lauder", "Coca-Cola", "PepsiCo",
    "IKEA", "Decathlon", "Skechers",
    # 金融 / 支付 / 保险
    "Visa", "Mastercard", "JPMorgan", "HSBC", "Citi", "Standard Chartered",
    "Allianz", "AIA", "BlackRock", "Stripe", "PayPal",
    # 医药 / 生物 / 医疗器械
    "Pfizer", "Roche", "Novartis", "AstraZeneca", "Merck", "Johnson & Johnson",
    "Medtronic", "Sanofi", "Biogen", "GSK",
    # 半导体 / 硬件 / 电子
    "Intel", "NVIDIA", "AMD", "Qualcomm", "Texas Instruments", "Applied Materials",
    "ASML", "Micron", "Samsung", "Sony",
    # 软件 / 云 / SaaS / AI
    "Microsoft", "SAP", "Oracle", "Salesforce", "ServiceNow", "Adobe", "Atlassian",
    "Databricks", "Snowflake", "OpenAI", "Anthropic", "Notion", "Linear",
    # 互联网 / 平台 / 游戏 / 娱乐
    "Airbnb", "Booking", "Uber", "Spotify", "Netflix", "Electronic Arts", "Ubisoft",
    "Riot Games", "Roblox",
    # 物流 / 航空 / 工程
    "DHL", "Maersk", "FedEx", "UPS", "Airbus",
    # 数据中心 / 通信
    "Equinix", "Cloudflare", "Cisco", "Ericsson", "Nokia",
    # —— 扩：外企100强补全（各行业龙头，机器猜 slug/eightfold + live 验证）——
    # 医药 / 医疗器械 / 生物
    "Eli Lilly", "Bristol Myers Squibb", "Takeda", "Bayer", "Boehringer Ingelheim",
    "Abbott", "Abbvie", "Amgen", "Gilead", "Moderna", "BD Becton Dickinson",
    "Stryker", "Boston Scientific", "Thermo Fisher", "Danaher", "Baxter", "Zoetis",
    # 半导体 / 电子 / 硬件
    "Broadcom", "Marvell", "NXP", "Infineon", "Analog Devices", "Lam Research",
    "KLA", "Skyworks", "Western Digital", "Seagate", "Keysight", "Arista Networks",
    "Dell Technologies", "HP", "HPE", "Logitech",
    # 汽车 / 零部件
    "Ford", "General Motors", "Stellantis", "Aptiv", "BorgWarner", "Magna",
    "ZF", "Michelin", "Goodyear", "Cummins", "PACCAR", "Garrett Motion",
    # 工业 / 能源 / 化工
    "General Electric", "GE Vernova", "GE HealthCare", "Johnson Controls",
    "Rockwell Automation", "Parker Hannifin", "Eaton", "Dover", "Illinois Tool Works",
    "Trane Technologies", "Carrier", "Otis", "Air Products", "Linde", "Dow",
    "DuPont", "Celanese", "Ecolab", "PPG", "Sherwin Williams", "Corning",
    "TE Connectivity", "Amphenol", "Schlumberger", "Halliburton", "Baker Hughes",
    # 消费 / 零售 / 食品 / 餐饮 / 奢侈
    "Mondelez", "Mars", "Kraft Heinz", "Kellanova", "General Mills", "Colgate Palmolive",
    "Kimberly Clark", "Mattel", "Hasbro", "VF Corporation", "Ralph Lauren", "Tapestry",
    "Levi Strauss", "Crocs", "Yum Brands", "Yum China", "Domino's", "Marriott",
    "Hilton", "Hyatt", "Booking Holdings", "Expedia",
    # 金融 / 支付 / 保险 / 评级
    "Goldman Sachs", "Morgan Stanley", "Bank of America", "Wells Fargo", "American Express",
    "BlackRock", "Blackstone", "KKR", "Apollo", "S&P Global", "Moody's", "MSCI",
    "Nasdaq", "CME Group", "Marsh McLennan", "Aon", "Prudential Financial", "MetLife",
    "Chubb", "Manulife", "Sun Life", "PayPal", "Block", "Fiserv", "Fidelity",
    # 软件 / 云 / SaaS / 数据 / AI / 安全
    "Workday", "Autodesk", "Intuit", "VMware", "Palo Alto Networks", "CrowdStrike",
    "Zscaler", "Okta", "MongoDB", "Confluent", "Elastic", "GitHub", "DocuSign",
    "Twilio", "Zoom", "Unity", "Roblox", "Pinterest", "Snap", "DoorDash", "Instacart",
    "Coinbase", "Robinhood", "Affirm", "Plaid", "Brex", "Ramp", "Rippling", "Figma",
    # 物流 / 航运 / 航空 / 工程
    "DSV", "Kuehne Nagel", "Expeditors", "CH Robinson", "Flexport", "Boeing",
    "GE Aerospace", "Honeywell Aerospace", "Raytheon", "Collins Aerospace",
    # 咨询 / 专业服务
    "Accenture", "Capgemini", "Cognizant", "Genpact", "Thomson Reuters", "RELX",
]


def build_discover_candidates():
    """对每个发现名自动生成候选：slug-ATS（greenhouse/lever/ashby/SR）+ eightfold（tenant+域名）。
    全部 live 验证，未命中自动丢弃（符合「禁止猜 slug 入库」——入库前提永远是 live 通过）。"""
    cands = []
    seen = set()

    def add(company, adapter, url, industry="discover"):
        if url in seen:
            return
        seen.add(url)
        cands.append({"company": company, "adapter": adapter, "industry": industry, "url": url})

    for name in _DISCOVER_NAMES:
        slugs = slugify(name)
        for platform in _DISCOVER_PLATFORMS:
            for slug in slugs:
                add(name, platform, _ATS_URL[platform](slug))
        # eightfold：compact slug 作 tenant，域名默认 {slug}.com（可被 _EF_DOMAINS 覆盖）
        compact = next((s for s in slugs if s.isalnum()), None)
        if compact:
            add(name, "eightfold", _eightfold_url(compact, _EF_DOMAINS.get(compact, f"{compact}.com")))
    return cands


# 外企单 host ATS：必须有**真实在华岗位**（is_china_location）才入库，否则只是全球/远程看板的噪声，
# 不符合「在华外企」雷达定位。本土 adapter（moka/beisen/company_spa）按构造即在华，只看 valid。
_FOREIGN_ATS = {"greenhouse", "lever", "ashby", "smartrecruiters", "workday", "eightfold", "oracle", "amazon"}


def probe_one(cand: dict, timeout: int = 15):
    adapter = ADAPTERS.get(cand["adapter"])
    if adapter is None:
        return {"ok": False, "valid": 0, "china": 0, "reason": f"unknown adapter {cand['adapter']}"}
    # 探活用较短超时，避免个别 host 挂起拖死整批（httpx 类适配器读 self.timeout）。
    try:
        adapter.timeout = timeout
    except Exception:
        pass
    try:
        html = adapter.fetch(cand["url"])
        raw_jobs = adapter.parse(html)
    except Exception as e:  # 探活失败（网络/反爬/结构不符）→ 丢弃，不入库
        return {"ok": False, "valid": 0, "china": 0, "reason": f"{type(e).__name__}: {e}"}

    valid = 0
    china = 0
    sample = None
    for raw in raw_jobs:
        if not raw.company:
            raw.company = cand["company"]
        is_valid, _ = normalizer.validate_job_quality(raw, cand["url"])
        if not is_valid:
            continue
        valid += 1
        if normalizer.is_china_location(raw.location):
            china += 1
            if china == 1:  # 优先用在华岗位做 sample
                sample = raw.jd_url
        elif sample is None:
            sample = raw.jd_url

    # 外企看板要求真实在华岗位；本土看板按构造即在华，valid 即可。
    ok = china > 0 if cand["adapter"] in _FOREIGN_ATS else valid > 0
    return {"ok": ok, "valid": valid, "china": china, "parsed": len(raw_jobs), "sample": sample}


def emit_sql(prefix: str, passed: list):
    lines = [
        f"-- {prefix} — 扩源（探活器 probe.py live 探活通过，仅含真返回岗位的源）",
        "-- 带 segment(模块)+industry(行业)。Idempotent: guarded by source_url.\n",
    ]
    for c in passed:
        cn = c.get("_china", 0)
        cn_txt = f"在华 {cn} 岗" if cn else f"{c['_valid']} 岗"
        industry = c.get("industry", "") or ""
        # segment：外企 ATS → foreign；本土 adapter 用候选自带 segment（默认 private）
        segment = "foreign" if c["adapter"] in _FOREIGN_ATS else c.get("segment", "private")
        notes = f"{c['company']}（{industry}，probe live 探活 {cn_txt}）".replace("'", "''")
        method = "http" if c["adapter"] in _HTTPX_ADAPTERS else "playwright"
        url = c["url"].replace("'", "''")
        company = c["company"].replace("'", "''")
        lines.append(
            "insert into sources (company, source_url, source_type, adapter_name, crawl_method, segment, industry, notes)\n"
            f"select '{company}', '{url}', 'official', '{c['adapter']}', '{method}', "
            f"'{segment}', '{industry}', '{notes}'\n"
            f"where not exists (select 1 from sources where source_url = '{url}');\n"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="扩源探活器")
    ap.add_argument("--all", action="store_true", help="连 playwright 类一起探（需装 playwright）")
    ap.add_argument("--discover", action="store_true",
                    help="发现模式：对内置跨行业公司名 × ATS 平台 × slug 变体自动生成候选并 live 验证（外企扩源主力）")
    ap.add_argument("--emit", type=str, default=None, help="探活通过的写迁移，传前缀如 026")
    ap.add_argument("--candidates", type=str, default=None, help="自定义候选 JSON 文件")
    args = ap.parse_args()

    cands = CANDIDATES
    if args.candidates:
        with open(args.candidates, encoding="utf-8") as f:
            cands = json.load(f)
    elif args.discover:
        # 发现模式：内置精选候选 + 自动猜 slug 候选（去重）。命中靠 live 验证，未命中自动丢弃。
        cands = CANDIDATES + build_discover_candidates()
        seen_urls = set()
        deduped = []
        for c in cands:
            if c["url"] in seen_urls:
                continue
            seen_urls.add(c["url"])
            deduped.append(c)
        cands = deduped

    if not args.all:
        cands = [c for c in cands if c["adapter"] in _HTTPX_ADAPTERS]

    passed = []
    print(f"[probe] 探活 {len(cands)} 个候选源...\n", flush=True)
    # discover 模式候选多，用较短超时控制总时长（探不到快速丢弃）
    probe_timeout = 8 if args.discover else 15
    for c in cands:
        r = probe_one(c, timeout=probe_timeout)
        flag = "✓" if r["ok"] else "✗"
        detail = (f"在华={r.get('china', 0)} valid={r['valid']} parsed={r.get('parsed', '-')} {r.get('sample', '')}"
                  if r["ok"] else r.get("reason", ""))
        if r["ok"]:
            print(f"  {flag} [{c['adapter']:15}] {c['company']:22} {detail}", flush=True)
            c = {**c, "_valid": r["valid"], "_china": r.get("china", 0)}
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
