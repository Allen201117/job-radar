"""SEC EDGAR 官方披露源（T2 铁事实）：ticker → CIK → submissions → listing 事实。

美股/ADR 上市公司（阿里 BABA / 拼多多 PDD / 京东 JD / 百度 BIDU 等）的官方上市确认 + 最新申报新鲜度。
按 Wikidata 已解析出的 ticker 精确取数（无模糊名匹配 → 不会误造事实）。
纯解析（find_cik / submissions_to_listing）与 HTTP（get_listing_by_ticker）分离，便于单测。
SEC 政策要求带可联系 User-Agent（SEC_EDGAR_UA env 可覆盖），否则数据中心 IP 易被限流。
"""
import os
from typing import Optional

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
EDGAR_COMPANY_URL = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                     "&CIK={cik}&type=&dateb=&owner=include&count=40")
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
# 营收 concept 名随 GAAP 版本变 → 依次尝试取首个有年度值的
_REVENUE_CONCEPTS = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")
UA = {"User-Agent": os.environ.get(
    "SEC_EDGAR_UA",
    "JobRadar/1.0 (https://github.com/Allen201117/job-radar; career-insights enrichment)")}
TIMEOUT = 25


def _norm_ticker(ticker) -> str:
    """去交易所前缀/空白、转大写（Wikidata ticker 偶带 'NYSE:' 前缀）。"""
    return str(ticker or "").split(":")[-1].strip().upper()


def find_cik(tickers_json: dict, ticker: str) -> Optional[str]:
    """company_tickers.json + ticker → 10 位零填充 CIK 串；查无返回 None。纯函数。"""
    t = _norm_ticker(ticker)
    if not t or not isinstance(tickers_json, dict):
        return None
    for row in tickers_json.values():
        if isinstance(row, dict) and str(row.get("ticker", "")).strip().upper() == t:
            try:
                return f"{int(row['cik_str']):010d}"
            except (KeyError, TypeError, ValueError):
                return None
    return None


def _latest_filing(recent: dict):
    """recent={form:[],filingDate:[]} → (form, date) 取最新日期那条；无则 (None, None)。"""
    forms = (recent or {}).get("form") or []
    dates = (recent or {}).get("filingDate") or []
    best = None
    for i in range(min(len(forms), len(dates))):
        d = dates[i]
        if d and (best is None or d > best[1]):
            best = (forms[i], d)
    return best or (None, None)


def submissions_to_listing(subs: dict, ticker: str) -> Optional[dict]:
    """submissions JSON → listing 维度 fact 草稿（origin=official，与 wikidata.facts_to_listing 同形）。
    无官方交易所信号返回 None（保守，守数据质量红线，不妄称上市）。纯函数。"""
    if not isinstance(subs, dict):
        return None
    name = str(subs.get("name") or "").strip()
    exchanges = [e for e in (subs.get("exchanges") or []) if e]
    if not name or not exchanges:
        return None
    ex = "/".join(dict.fromkeys(exchanges))
    tk = _norm_ticker(ticker) or (subs.get("tickers") or [None])[0]
    form, date = _latest_filing((subs.get("filings") or {}).get("recent"))
    fresh = f"，最新申报 {form}（{date}）" if form and date else ""
    cik = str(subs.get("cik") or "").strip()
    return {
        "dimension": "listing", "grade": "fact",
        "title": "上市状态 · SEC 官方披露",
        "content": f"据 SEC EDGAR 官方披露，{name} 在美国证监会持续申报{fresh}，挂牌于 {ex}（代码 {tk}）。",
        "payload": {"status": "listed", "exchange": ex, "ticker": tk,
                    "latest_form": form, "latest_filing_date": date},
        "origin": "official",
        "source_url": EDGAR_COMPANY_URL.format(cik=cik) if cik else TICKERS_URL,
        "source_publisher": "SEC EDGAR",
    }


# ---------- 业绩（XBRL companyfacts）：营收/净利/同比/员工 ----------

def _annual_series(facts: dict, concept: str, unit: str = "USD"):
    """某 concept 的年度(FY/10-K等)值序列 [(fy, val, end)]，按 end 升序。纯函数。"""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"][unit]
    except (KeyError, TypeError):
        return []
    out = []
    for it in units:
        if (it.get("fp") == "FY" and it.get("form") in _ANNUAL_FORMS
                and isinstance(it.get("val"), (int, float)) and it.get("end")):
            out.append((it.get("fy"), it["val"], it["end"]))
    out.sort(key=lambda x: x[2])
    return out


def _latest_employees(facts: dict) -> Optional[int]:
    try:
        units = facts["facts"]["dei"]["EntityNumberOfEmployees"]["units"]["pure"]
    except (KeyError, TypeError):
        return None
    vals = [(it["end"], it["val"]) for it in units
            if isinstance(it.get("val"), (int, float)) and it.get("end")]
    if not vals:
        return None
    vals.sort()
    return int(vals[-1][1])


def financials_from_companyfacts(facts) -> Optional[dict]:
    """EDGAR companyfacts JSON → 最近财年 营收/净利/营收同比/员工。无可用值返回 None。纯函数。"""
    if not isinstance(facts, dict):
        return None
    rev_series = []
    for c in _REVENUE_CONCEPTS:
        rev_series = _annual_series(facts, c)
        if rev_series:
            break
    ni_series = _annual_series(facts, "NetIncomeLoss")
    emp = _latest_employees(facts)
    if not rev_series and not ni_series and emp is None:
        return None
    rev = rev_series[-1] if rev_series else None
    rev_prev = rev_series[-2] if len(rev_series) >= 2 else None
    yoy = (round((rev[1] - rev_prev[1]) / abs(rev_prev[1]) * 100)
           if rev and rev_prev and rev_prev[1] else None)
    ni = ni_series[-1] if ni_series else None
    return {
        "fy": rev[0] if rev else (ni[0] if ni else None),
        "revenue": rev[1] if rev else None,
        "net_income": ni[1] if ni else None,
        "revenue_yoy_pct": yoy,
        "employees": emp,
    }


def _fmt_usd(v) -> Optional[str]:
    if v is None:
        return None
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B 美元"
    if a >= 1e6:
        return f"{v / 1e6:.0f}M 美元"
    return f"{v:.0f} 美元"


def financials_sentence(fin: dict) -> str:
    """业绩事实正文（追加到 listing item）。无可用字段返回空串。"""
    parts = []
    if fin.get("revenue") is not None:
        parts.append(f"营收约 {_fmt_usd(fin['revenue'])}")
    if fin.get("net_income") is not None:
        parts.append(f"净利 {_fmt_usd(fin['net_income'])}")
    if fin.get("revenue_yoy_pct") is not None:
        parts.append(f"营收同比 {fin['revenue_yoy_pct']:+d}%")
    if fin.get("employees"):
        parts.append(f"员工约 {fin['employees']} 人")
    if not parts:
        return ""
    fy = f"FY{fin['fy']} " if fin.get("fy") else ""
    return f"据 SEC 财报（{fy}）：{'，'.join(parts)}。"


def get_listing_by_ticker(ticker: str, client: Optional[httpx.Client] = None) -> Optional[dict]:
    """ticker → CIK → submissions → listing 事实。失败/查无返回 None（静默，与 wikidata 同口径）。"""
    t = _norm_ticker(ticker)
    if not t:
        return None
    own = client or httpx.Client()
    try:
        r = own.get(TICKERS_URL, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        cik = find_cik(r.json(), t)
        if not cik:
            return None
        r2 = own.get(SUBMISSIONS_URL.format(cik=cik), headers=UA, timeout=TIMEOUT)
        r2.raise_for_status()
        li = submissions_to_listing(r2.json(), t)
        if li:
            try:  # 业绩（companyfacts）：失败不影响上市事实本身，折进同一 listing 卡片
                r3 = own.get(COMPANYFACTS_URL.format(cik=cik), headers=UA, timeout=TIMEOUT)
                if r3.status_code < 300:
                    fin = financials_from_companyfacts(r3.json())
                    if fin:
                        li["payload"]["financials"] = fin
                        sent = financials_sentence(fin)
                        if sent:
                            li["content"] = li["content"] + " " + sent
            except Exception as e:
                print(f"  [edgar-fin-err] {t}: {type(e).__name__}: {str(e)[:120]}")
        return li
    except Exception as e:
        print(f"  [edgar-err] {t}: {type(e).__name__}: {str(e)[:140]}")
        return None
    finally:
        if client is None:
            own.close()
