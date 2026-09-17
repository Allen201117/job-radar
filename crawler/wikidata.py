"""T2 官方事实层 — Wikidata 免费公开端点客户端（CC0，零付费）。

只用免费 Action API（www.wikidata.org/w/api.php），**禁用**付费 Wikimedia Enterprise。
职责：公司名 → 结构化事实（上市状态 / 交易所 / 代码 / 成立年 / 员工规模 / 总部 / 行业）。
纯解析（parse_company_facts / facts_to_listing / headcount_band）与 HTTP（get_company_facts）分离，便于单测。

httpx 默认 trust_env=True → 自动走 HTTPS_PROXY 环境变量（本机经 Clash 验证，CI 直连）。
"""
import re
import threading
import time
from typing import Optional

import httpx

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikimedia UA 政策要求带可联系的 URL/邮箱，否则数据中心 IP 易被 403/429（CI 实测全 noface 的根因排查）。
UA = {"User-Agent": "JobRadar/1.0 (https://github.com/Allen201117/job-radar; career-insights enrichment)"}
TIMEOUT = 25
POLITE_DELAY = 0.2  # 每请求后小憩，对 Wikimedia 礼貌 + 降低被限流概率
# 每家公司最多试几个候选名：候选越多命中越高，但请求量线性上涨，而 Wikimedia 会 429
# （2026-09-09~11 实测被限流 1,504 次）。4 个足够覆盖「全称 / 去括号 / 去法定后缀 / 中英拆分」。
_MAX_NAME_VARIANTS = 4
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5
_RATE_LOCK = threading.Lock()
_LAST_CALL_AT = 0.0

# instance-of（P31）里代表「上市公司」的 QID（命中即视为已上市，与有无交易所互为佐证）
_PUBLIC_COMPANY_QIDS = {"Q891723"}  # public company
# 证券交易所 QID → 简称（用于 listing 正文，避免再查一次 label）
_EXCHANGE_NAMES = {
    "Q13677": "纽交所", "Q82059": "纳斯达克", "Q174687": "纳斯达克",
    "Q739514": "港交所", "Q496672": "港交所", "Q1377551": "港交所",
    "Q517750": "上交所", "Q2038986": "深交所", "Q1547564": "上交所",
    "Q11705": "纽交所", "Q487907": "伦交所", "Q200402": "东京证交所",
}


# ---------- 纯解析（单测覆盖；输入已抓回的 entity JSON + 引用 QID→label 表） ----------

def _claim_items(entity: dict, pid: str) -> list:
    out = []
    for c in (entity.get("claims", {}) or {}).get(pid, []) or []:
        try:
            dv = c["mainsnak"]["datavalue"]["value"]
            if isinstance(dv, dict) and dv.get("id"):
                out.append(dv["id"])
        except (KeyError, TypeError):
            continue
    return out


def _claim_strings(entity: dict, pid: str) -> list:
    out = []
    for c in (entity.get("claims", {}) or {}).get(pid, []) or []:
        try:
            dv = c["mainsnak"]["datavalue"]["value"]
            if isinstance(dv, str):
                out.append(dv)
        except (KeyError, TypeError):
            continue
    return out


def _claim_year(entity: dict, pid: str) -> Optional[int]:
    for c in (entity.get("claims", {}) or {}).get(pid, []) or []:
        try:
            t = c["mainsnak"]["datavalue"]["value"]["time"]  # "+2014-04-00T00:00:00Z"
            m = re.match(r"[+-](\d{4})", t)
            if m and int(m.group(1)) > 1800:
                return int(m.group(1))
        except (KeyError, TypeError):
            continue
    return None


def _claim_employees(entity: dict) -> Optional[int]:
    """P1128 员工数：取「point in time(P585)」最新的一条；无限定符则取首条。"""
    best, best_year = None, -1
    for c in (entity.get("claims", {}) or {}).get("P1128", []) or []:
        try:
            n = int(float(c["mainsnak"]["datavalue"]["value"]["amount"]))
        except (KeyError, TypeError, ValueError):
            continue
        yr = 0
        for q in (c.get("qualifiers", {}) or {}).get("P585", []) or []:
            try:
                m = re.match(r"[+-](\d{4})", q["datavalue"]["value"]["time"])
                if m:
                    yr = int(m.group(1))
            except (KeyError, TypeError):
                continue
        if yr >= best_year:
            best, best_year = n, yr
    return best


def headcount_band(n: Optional[int]) -> Optional[str]:
    """员工数 → 规模档（稳定、抗小幅变动；不落精确数避免易过时）。"""
    if not n or n <= 0:
        return None
    steps = [(100, "1-100"), (500, "100-500"), (1000, "500-1000"),
             (5000, "1000-5000"), (10000, "5000-1万"), (50000, "1万-5万"),
             (100000, "5万-10万"), (10**9, "10万+")]
    for cap, label in steps:
        if n < cap:
            return label
    return "10万+"


def parse_company_facts(entity: dict, label_map: dict) -> dict:
    """把一个 Wikidata entity + 引用 QID→中文 label 表，解析为结构化事实 dict。纯函数。"""
    qid = entity.get("id")
    labels = entity.get("labels", {}) or {}
    label = (labels.get("zh-hans") or labels.get("zh") or labels.get("en") or {}).get("value") or qid

    instance_of = _claim_items(entity, "P31")
    exchange_qids = _claim_items(entity, "P414")
    tickers = _claim_strings(entity, "P249")
    official_sites = _claim_strings(entity, "P856")
    founded_year = _claim_year(entity, "P571")
    employees = _claim_employees(entity)
    hq_qids = _claim_items(entity, "P159")
    industry_qids = _claim_items(entity, "P452")

    listed = bool(exchange_qids) or any(q in _PUBLIC_COMPANY_QIDS for q in instance_of)
    exchanges = [_EXCHANGE_NAMES.get(q) or label_map.get(q) for q in exchange_qids]
    exchanges = list(dict.fromkeys(e for e in exchanges if e))  # 去重保序（多 QID 映射同交易所，如港交所有多个 QID）
    hq = next((label_map.get(q) for q in hq_qids if label_map.get(q)), None)
    industry = next((label_map.get(q) for q in industry_qids if label_map.get(q)), None)

    return {
        "qid": qid,
        "label": label,
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
        "listed": listed,
        "exchanges": exchanges,
        "ticker": tickers[0] if tickers else None,
        "official_site": official_sites[0] if official_sites else None,
        "founded_year": founded_year,
        "employees": employees,
        "headcount_band": headcount_band(employees),
        "hq": hq,
        "industry": industry,
        # 解析时需要二次查 label 的引用 QID（供编排层批量取 label 用）
        "_ref_qids": list({*exchange_qids, *hq_qids, *industry_qids}),
    }


def facts_to_listing(facts: dict) -> Optional[dict]:
    """把事实映射为 listing 维度 insight_item 草稿（fact 级，origin=wikidata）。
    严守红线：不落股价/市值等易变数字，只陈述稳定事实 + payload。无足够信号返回 None。"""
    listed = facts.get("listed")
    ex = facts.get("exchanges") or []
    ticker = facts.get("ticker")
    if not listed and not facts.get("founded_year"):
        return None
    if listed:
        where = ("、".join(ex) or "公开市场")
        tail = f"（{('/'.join(ex))} {ticker}）" if ticker and ex else (f"（代码 {ticker}）" if ticker else "")
        content = f"据 Wikidata 公开资料，{facts['label']} 为已上市公司，挂牌于{where}{tail}。"
        status = "listed"
    else:
        content = f"据 Wikidata 公开资料，{facts['label']} 当前未见公开上市记录（未上市 / 未在主要交易所挂牌）。"
        status = "private"
    return {
        "dimension": "listing",
        "grade": "fact",
        "title": "上市状态 · 据公开资料",
        "content": content,
        "payload": {
            "status": status,
            "exchange": ("/".join(ex) or None),
            "ticker": ticker,
        },
        "origin": "wikidata",
        "source_url": facts.get("wikidata_url"),
        "source_publisher": "Wikidata",
    }


def facts_to_profile(facts: dict) -> dict:
    """把事实映射为 company_profiles 可回填的列（成立年 / 规模档 / 融资阶段 / 总部）。"""
    out = {}
    if facts.get("founded_year"):
        out["founded_year"] = facts["founded_year"]
    if facts.get("headcount_band"):
        out["headcount_band"] = facts["headcount_band"]
    if facts.get("hq"):
        out["hq_location"] = facts["hq"]
    out["funding_stage"] = "已上市" if facts.get("listed") else "未上市/未披露"
    return out


# ---------- 公司名归一：库里存的是实体全称，Wikidata 收的是品牌短名 ----------
# 实测（2026-09-17，25 家 T2 死信公司 live 探）：直接拿库里名字搜，16 家 `wbsearchentities` 零命中，
# 而它们里「盐津铺子食品股份有限公司 / 雅迪科技集团 / 霸王茶姬（北京）餐饮管理有限公司 / 华润三九 999」
# 这类**只是名字形态不同**，Wikidata 其实收了品牌短名。所以先把全称降解成候选短名再搜。
_RECRUIT_TOKENS = ("实习", "校招", "社招", "招聘", "校园招聘", "实习生")
# 长的排前面：逐个尝试剥离时必须先剥「股份有限公司」再剥「公司」，否则会剩下「…股份有限」。
_LEGAL_SUFFIXES = (
    "股份有限责任公司", "股份有限公司", "有限责任公司", "集团股份公司", "控股集团有限公司",
    "集团有限公司", "控股有限公司", "有限公司", "股份公司", "集团公司", "科技集团",
    "控股集团", "公司", "集团", "控股",
)
_PAREN_RE = re.compile(r"[（(]([^（()）]*)[)）]")
# 括号里是地名/行政区时只是注册地，不是品牌（「天玺（北京）文化科技」的「北京」）；
# 而「（万代南梦宫）」这种才是真正想要的品牌名。
_REGION_HINTS = ("省", "市", "区", "县", "自治", "中国", "上海", "北京", "深圳", "广州", "杭州",
                 "成都", "重庆", "天津", "苏州", "南京", "武汉", "西安", "香港", "亚太", "中国区")


def _strip_legal_suffix(text: str) -> str:
    """反复剥离尾部公司法定后缀，直到不再变化。纯函数。"""
    cur = (text or "").strip()
    while True:
        for suf in _LEGAL_SUFFIXES:
            if len(cur) > len(suf) and cur.endswith(suf):
                cur = cur[: -len(suf)].strip()
                break
        else:
            return cur


def name_variants(name: str) -> list:
    """公司名 → 递降候选名列表（原名恒在第一位，按「越具体越靠前」排，去重）。纯函数。

    只做**减法**（剥招聘后缀 / 括号 / 法定后缀 / 拆中英混写），不凭空造名字 ——
    造名字就是猜，猜 = 张冠李戴（本仓库立过碑的红线）。命中与否另有 `plausible_company_hit` 把关。
    """
    base = (name or "").strip()
    if not base:
        return []
    out, seen = [], set()

    def push(value: str):
        v = (value or "").strip(" ·-—_、,，")
        if len(v) < 2 or v in seen:
            return
        seen.add(v)
        out.append(v)

    push(base)
    # ① 括号里的品牌名（非地名）单独作为候选：「天玺（北京）…（万代南梦宫）」→「万代南梦宫」
    parens = [m.strip() for m in _PAREN_RE.findall(base)]
    brand_parens = [p for p in parens if p and not any(h in p for h in _REGION_HINTS)]
    # ② 主干：去掉所有括号 + 去掉尾部招聘词
    trunk = _PAREN_RE.sub("", base).strip()
    for token in _RECRUIT_TOKENS:
        if trunk.endswith(token):
            trunk = trunk[: -len(token)].strip()
    for p in brand_parens:
        push(_strip_legal_suffix(p))
    push(trunk)
    push(_strip_legal_suffix(trunk))
    # ③ 中英混写拆开：「安克创新 Anker」「华润三九 999」→ 两段各自再试。
    # ⚠️ 拆出来的**纯西文短片段一律不要**：live 实测「陶氏化学 Dow」拆出的 `Dow` 命中了
    # 美国国防部（它的别名里有 DOW），字段是 hq=五角大楼 / emp=287 万。三四个字母的缩写
    # 在 Wikidata 的别名空间里必然撞车，收益远小于一次张冠李戴的代价。
    for piece in re.split(r"[\s/|]+", _strip_legal_suffix(trunk)):
        piece = piece.strip()
        if not piece or piece.isdigit():
            continue
        if piece.isascii() and len(piece) < 5:
            continue
        push(_strip_legal_suffix(piece))
    return out


def _normalize_for_match(text: str) -> str:
    """比名字用的归一：**先剥法定后缀**，再去空白/分隔符、折叠大小写。纯函数。

    两边都剥是必要的：Wikidata 的中文别名常写「国家电网公司」而库里写「国家电网」，
    不剥就只能判不等 → 一批本来查得到的公司被这道门挡掉（2026-09-17 B 池对拍实测）。
    仍然只判**相等**，不判包含（`京东` ⊂ `京东方` 是本仓库立过碑的红线）。
    """
    cleaned = re.sub(r"[\s·・\-—_.、,，'’\"]+", "", str(text or ""))
    return _strip_legal_suffix(cleaned).casefold() or cleaned.casefold()


def plausible_company_hit(query: str, hit: dict) -> bool:
    """搜索命中是否可采信 = 归一后**完全相等**（label / 别名 / match.text 任一）。纯函数。

    ⚠️ 刻意不做子串包含：`京东` ⊂ `京东方` 这条红线在本仓库写过碑，用包含判等于把
    张冠王戴的门自己拆了。宁可漏判（回退旧行为，见 search_qid）也不错判。
    """
    q = _normalize_for_match(query)
    if not q:
        return False
    match = hit.get("match") or {}
    # 短的纯西文名（TCL / Dow / NXP…）只认**正式标签**命中，不认别名：Wikidata 的别名空间里
    # 三四个字母的缩写必然撞车（`DOW` 是美国国防部的别名、`Tcl` 是编程语言的标签）。
    strict_label_only = q.isascii() and len(q) < 5
    if strict_label_only and match.get("type") not in (None, "label"):
        return False
    cands = [hit.get("label"), match.get("text")]
    if not strict_label_only:
        cands.extend(hit.get("aliases") or [])
    return any(_normalize_for_match(c) == q for c in cands if c)


# 只靠「名字对得上」远远不够：2026-09-17 live 实测，名字精确相等仍会把
# `TCL`→Tcl（编程语言）、`Rockwell`→Norman Rockwell（画家）、`Dcar`→欧洲议会某代表团、
# `Automation`→「自动化」这个概念 收进来。**原实现连名字都不比、直接取 hits[0]，更宽。**
# 所以再加一道实体类型门：拿到实体后必须看起来真是个「组织」，否则弃权。
_HUMAN_QIDS = {"Q5"}
_ORG_QIDS = {
    "Q4830453",   # business
    "Q783794",    # company
    "Q6881511",   # enterprise
    "Q891723",    # public company
    "Q1589009",   # privately held company
    "Q219577",    # holding company
    "Q161726",    # multinational corporation
    "Q43229",     # organization
    "Q167037",    # corporation
    "Q270791",    # state-owned enterprise
    "Q18388277",  # technology company
    "Q22687",     # bank
    "Q46970",     # airline
    "Q163740",    # nonprofit organization
    "Q210167",    # video game developer
    "Q786820",    # automobile manufacturer
    "Q507619",    # retail chain
    "Q1058914",   # software company
}
# 组织专属属性：人 / 概念 / 编程语言都不会有这些。白名单必然不全，靠它兜底，
# 比把白名单越堆越长可靠（堆得再长也证明不了「全」）。
_ORG_ONLY_PROPS = ("P452", "P414", "P1128", "P159", "P1454", "P2139")


def is_company_entity(entity: dict) -> bool:
    """实体看起来是不是「组织/公司」。纯函数，输入 wbgetentities 的单个 entity。

    判据：P31 命中组织白名单，或带有组织专属属性（行业 / 交易所 / 员工数 / 总部 / 法律形式 / 营收）。
    P31 里有「人」一律否决——名字撞人名是这套降解检索最容易犯的错。
    """
    if not isinstance(entity, dict):
        return False
    p31 = set(_claim_items(entity, "P31"))
    if p31 & _HUMAN_QIDS:
        return False
    if p31 & _ORG_QIDS:
        return True
    claims = entity.get("claims", {}) or {}
    return any(claims.get(p) for p in _ORG_ONLY_PROPS)


# ---------- HTTP 编排（live；单测以 mock client 覆盖） ----------

def _throttle():
    """全进程串行节流：多线程各自 sleep(0.2) 等于**没有**节流 —— 4 个线程就是 4 倍速率，
    这正是 2026-09-09~11 三晚被 Wikidata 429 限流 1,504 次的原因。锁 + 全局时间戳才算数。"""
    global _LAST_CALL_AT
    with _RATE_LOCK:
        gap = time.monotonic() - _LAST_CALL_AT
        if gap < POLITE_DELAY:
            time.sleep(POLITE_DELAY - gap)
        _LAST_CALL_AT = time.monotonic()


def _get(params: dict, client: httpx.Client) -> dict:
    p = {"format": "json", **params}
    last_exc = None
    for attempt in range(_MAX_RETRIES):
        _throttle()
        try:
            r = client.get(WIKIDATA_API, params=p, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code
            if status not in _RETRY_STATUS or attempt == _MAX_RETRIES - 1:
                raise
            # 被限流时对方常给 Retry-After；不看它硬重试只会继续挨打。
            try:
                wait = float(e.response.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0.0
            time.sleep(max(wait, _BACKOFF_BASE * (2 ** attempt)))
    raise last_exc  # pragma: no cover - 循环里必然 return 或 raise


def search_qid(name: str, client: httpx.Client) -> Optional[str]:
    """按名搜实体，返回最可能的公司 QID（取首个命中；Wikidata 搜索已按相关性排序）。

    ⚠️ 这是**旧的宽松口径**，只保留给单测与调用方兼容；`get_company_facts` 已改走
    `search_qid_candidates` + 名字门 + 实体类型门。别在新代码里用它。
    """
    if not name or not name.strip():
        return None
    for lang in ("zh", "en"):
        data = _get({"action": "wbsearchentities", "search": name.strip(),
                     "language": lang, "type": "item", "limit": 5}, client)
        hits = data.get("search") or []
        if hits:
            return hits[0]["id"]
    return None


def search_qid_candidates(name: str, client: httpx.Client, max_hits: int = 3) -> list:
    """按名搜实体，返回**名字对得上**的 QID 列表（可能为空）。相关性序保留。"""
    if not name or not name.strip():
        return []
    out = []
    for lang in ("zh", "en"):
        data = _get({"action": "wbsearchentities", "search": name.strip(),
                     "language": lang, "type": "item", "limit": 5}, client)
        for hit in data.get("search") or []:
            qid = hit.get("id")
            if qid and qid not in out and plausible_company_hit(name, hit):
                out.append(qid)
                if len(out) >= max_hits:
                    return out
    return out


def _fetch_entity(qid: str, client: httpx.Client) -> Optional[dict]:
    data = _get({"action": "wbgetentities", "ids": qid,
                 "props": "claims|labels", "languages": "zh|zh-hans|en"}, client)
    return (data.get("entities") or {}).get(qid)


def get_company_facts(name: str, aliases: Optional[list] = None,
                      client: Optional[httpx.Client] = None) -> Optional[dict]:
    """公司名（+别名）→ 结构化事实 dict，失败/查无返回 None。"""
    own = client or httpx.Client()
    try:
        # 候选名 = 每个输入名（库里全称 + 别名）各自降解出的短名，按「越具体越靠前」。
        # 逐个搜 → 名字门 → 实体类型门，第一个两道门都过的才采信；全不过 = 查无（noface），
        # **不再退回 hits[0]**（那正是 TCL→Tcl 编程语言这类张冠李戴的来源）。
        candidates, seen_names = [], set()
        for raw in [name, *(aliases or [])]:
            for variant in name_variants(raw):
                if variant not in seen_names:
                    seen_names.add(variant)
                    candidates.append(variant)
        entity, qid, tried_qids = None, None, set()
        for variant in candidates[:_MAX_NAME_VARIANTS]:
            for cand_qid in search_qid_candidates(variant, own):
                if cand_qid in tried_qids:
                    continue
                tried_qids.add(cand_qid)
                cand_entity = _fetch_entity(cand_qid, own)
                if cand_entity and is_company_entity(cand_entity):
                    entity, qid = cand_entity, cand_qid
                    break
            if entity:
                break
        if not entity:
            print(f"  [wd-noqid] {name}")
            return None
        # 先解析一次拿到引用 QID，再批量取它们的中文 label，重解析以填 exchange/hq/industry 名
        prelim = parse_company_facts(entity, {})
        ref = prelim.get("_ref_qids") or []
        label_map = {}
        if ref:
            lbl_data = _get({"action": "wbgetentities", "ids": "|".join(ref[:40]),
                             "props": "labels", "languages": "zh|zh-hans|en"}, own)
            for q, e in (lbl_data.get("entities") or {}).items():
                lbs = e.get("labels", {}) or {}
                label_map[q] = (lbs.get("zh-hans") or lbs.get("zh") or lbs.get("en") or {}).get("value")
        facts = parse_company_facts(entity, label_map)
        facts.pop("_ref_qids", None)
        return facts
    finally:
        if client is None:
            own.close()
