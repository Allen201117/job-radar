"""巨潮资讯（cninfo）A 股官方披露源（T2 铁事实）：公司名 → A 股简称匹配 → 代码 + 交易所 → listing 事实。

巨潮 = 中国证监会指定信息披露平台，覆盖 A 股（比亚迪/顺丰这类本土公司，EDGAR 不覆盖）。
**默认关闭**（INSIGHT_CNINFO_ENABLED），守"禁猜入库"：沙箱连不上、无法 live 验证返回格式，
须用户开启后跑一次 T2 眼验正确再放行。纯解析（find_stock/exchange_from_code/stock_to_listing）可单测。
"""
import os
from typing import Optional

import httpx

# 巨潮全 A 股列表（含沪深；历史上 szse_stock.json 即全量）。上线前须 live 复核此端点与字段。
SZSE_STOCK_URL = "http://www.cninfo.com.cn/new/data/szse_stock.json"
COMPANY_URL = "http://www.cninfo.com.cn/new/disclosure/stock?stockCode={code}&orgId={org}"
UA = {"User-Agent": "JobRadar/1.0 (https://github.com/Allen201117/job-radar; career-insights)"}
TIMEOUT = 20

_SUFFIXES = ("股份有限公司", "有限公司", "集团股份", "控股集团", "股份", "集团", "控股", "公司")


def enabled() -> bool:
    """默认关闭；INSIGHT_CNINFO_ENABLED=true/1/yes 才启用（守禁猜入库，待 live 验证后开）。"""
    return str(os.environ.get("INSIGHT_CNINFO_ENABLED", "")).strip().lower() in ("1", "true", "yes")


def exchange_from_code(code) -> str:
    """A 股代码前缀 → 交易所简称；未知返回 ''。"""
    c = str(code or "").strip()
    if c[:2] in ("60", "68"):
        return "上交所"
    if c[:2] in ("00", "30"):
        return "深交所"
    if c[:1] in ("8", "4") or c[:2] == "92":
        return "北交所"
    return ""


def _strip_name(s) -> str:
    s = str(s or "").strip()
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return s.strip()


def find_stock(stock_list, name) -> Optional[dict]:
    """按公司名严格匹配 A 股简称（zwjc）：精确 或 去后缀后相等。纯函数，宁缺毋滥防误配。"""
    n = str(name or "").strip()
    if not isinstance(stock_list, list) or not n:
        return None
    ns = _strip_name(n)
    for row in stock_list:
        if not isinstance(row, dict):
            continue
        z = str(row.get("zwjc") or "").strip()
        if not z:
            continue
        if z == n or (ns and _strip_name(z) == ns):
            return row
    return None


def stock_to_listing(stock) -> Optional[dict]:
    """A 股记录 → listing 维度 fact（origin=official，与 wikidata.facts_to_listing 同形）。纯函数。"""
    if not isinstance(stock, dict):
        return None
    code = str(stock.get("code") or "").strip()
    zwjc = str(stock.get("zwjc") or "").strip()
    if not code or not zwjc:
        return None
    ex = exchange_from_code(code) or "A股"
    org = str(stock.get("orgId") or "").strip()
    return {
        "dimension": "listing", "grade": "fact",
        "title": "上市状态 · 巨潮资讯（官方披露）",
        "content": f"据巨潮资讯网（中国证监会指定披露平台），{zwjc} 为 A 股上市公司，股票代码 {code}（{ex}）。",
        "payload": {"status": "listed", "exchange": ex, "ticker": code},
        "origin": "official",
        "source_url": COMPANY_URL.format(code=code, org=org),
        "source_publisher": "巨潮资讯",
    }


def get_listing_by_name(name, aliases=None, client=None) -> Optional[dict]:
    """公司名（+别名）→ A 股 listing 事实。未启用/失败/查无返回 None（静默）。"""
    own = client or httpx.Client()
    try:
        r = own.get(SZSE_STOCK_URL, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        stocks = data.get("stockList") if isinstance(data, dict) else None
        if not isinstance(stocks, list):
            return None
        for cand in [name, *(aliases or [])]:
            st = find_stock(stocks, cand)
            if st:
                return stock_to_listing(st)
        return None
    except Exception as e:
        print(f"  [cninfo-err] {name}: {type(e).__name__}: {str(e)[:140]}")
        return None
    finally:
        if client is None:
            own.close()
