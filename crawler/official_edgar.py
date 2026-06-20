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
        return submissions_to_listing(r2.json(), t)
    except Exception as e:
        print(f"  [edgar-err] {t}: {type(e).__name__}: {str(e)[:140]}")
        return None
    finally:
        if client is None:
            own.close()
