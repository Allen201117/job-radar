"""T2 官方事实层 — Wikidata 免费公开端点客户端（CC0，零付费）。

只用免费 Action API（www.wikidata.org/w/api.php），**禁用**付费 Wikimedia Enterprise。
职责：公司名 → 结构化事实（上市状态 / 交易所 / 代码 / 成立年 / 员工规模 / 总部 / 行业）。
纯解析（parse_company_facts / facts_to_listing / headcount_band）与 HTTP（get_company_facts）分离，便于单测。

httpx 默认 trust_env=True → 自动走 HTTPS_PROXY 环境变量（本机经 Clash 验证，CI 直连）。
"""
import re
import time
from typing import Optional

import httpx

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# Wikimedia UA 政策要求带可联系的 URL/邮箱，否则数据中心 IP 易被 403/429（CI 实测全 noface 的根因排查）。
UA = {"User-Agent": "JobRadar/1.0 (https://github.com/Allen201117/job-radar; career-insights enrichment)"}
TIMEOUT = 25
POLITE_DELAY = 0.2  # 每请求后小憩，对 Wikimedia 礼貌 + 降低被限流概率

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
    label = (labels.get("zh") or labels.get("zh-hans") or labels.get("en") or {}).get("value") or qid

    instance_of = _claim_items(entity, "P31")
    exchange_qids = _claim_items(entity, "P414")
    tickers = _claim_strings(entity, "P249")
    founded_year = _claim_year(entity, "P571")
    employees = _claim_employees(entity)
    hq_qids = _claim_items(entity, "P159")
    industry_qids = _claim_items(entity, "P452")

    listed = bool(exchange_qids) or any(q in _PUBLIC_COMPANY_QIDS for q in instance_of)
    exchanges = [_EXCHANGE_NAMES.get(q) or label_map.get(q) for q in exchange_qids]
    exchanges = [e for e in exchanges if e]
    hq = next((label_map.get(q) for q in hq_qids if label_map.get(q)), None)
    industry = next((label_map.get(q) for q in industry_qids if label_map.get(q)), None)

    return {
        "qid": qid,
        "label": label,
        "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else None,
        "listed": listed,
        "exchanges": exchanges,
        "ticker": tickers[0] if tickers else None,
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


# ---------- HTTP 编排（live；单测以 mock client 覆盖） ----------

def _get(params: dict, client: httpx.Client) -> dict:
    p = {"format": "json", **params}
    r = client.get(WIKIDATA_API, params=p, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    time.sleep(POLITE_DELAY)
    return r.json()


def search_qid(name: str, client: httpx.Client) -> Optional[str]:
    """按名搜实体，返回最可能的公司 QID（取首个命中；Wikidata 搜索已按相关性排序）。"""
    if not name or not name.strip():
        return None
    for lang in ("zh", "en"):
        data = _get({"action": "wbsearchentities", "search": name.strip(),
                     "language": lang, "type": "item", "limit": 5}, client)
        hits = data.get("search") or []
        if hits:
            return hits[0]["id"]
    return None


def get_company_facts(name: str, aliases: Optional[list] = None,
                      client: Optional[httpx.Client] = None) -> Optional[dict]:
    """公司名（+别名）→ 结构化事实 dict，失败/查无返回 None。"""
    own = client or httpx.Client()
    try:
        qid = None
        for cand in [name, *(aliases or [])]:
            qid = search_qid(cand, own)
            if qid:
                break
        if not qid:
            print(f"  [wd-noqid] {name}")
            return None
        ent_data = _get({"action": "wbgetentities", "ids": qid,
                         "props": "claims|labels", "languages": "zh|zh-hans|en"}, own)
        entity = (ent_data.get("entities") or {}).get(qid)
        if not entity:
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
                label_map[q] = (lbs.get("zh") or lbs.get("zh-hans") or lbs.get("en") or {}).get("value")
        facts = parse_company_facts(entity, label_map)
        facts.pop("_ref_qids", None)
        return facts
    finally:
        if client is None:
            own.close()
