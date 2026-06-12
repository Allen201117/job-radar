"""百度千帆 Web Search — Python 客户端 + 每日额度守卫（T3 经验层的接地检索源）。

口径与 lib/baidu-qianfan-search.js 完全一致（同端点 / 鉴权 / 请求体 / 响应解析）。
千帆免费「百度搜索」每日 50 次（全局额度）→ 走 qianfan_usage 表做**跨 CI run 持久**的当日计数，
自封顶 QIANFAN_DAILY_CAP（默认 40，留余量给 /api/discovery 的交互用量），绝不冲破 50。
respects BAIDU_QIANFAN_SEARCH_DISABLED 熔断 + 缺 key 静默降级（返回 []）。
"""
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

WEB_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
DEFAULT_TOP_K = 8
TIMEOUT = 12
DAILY_CAP = int(os.environ.get("QIANFAN_DAILY_CAP", "40"))  # 自封顶，留 ~10 给 /api/discovery


def is_disabled():
    return bool(re.match(r"^(1|true|yes)$", str(os.environ.get("BAIDU_QIANFAN_SEARCH_DISABLED", "")), re.I))


def is_configured():
    return bool(os.environ.get("BAIDU_QIANFAN_API_KEY")) and not is_disabled()


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def budget_used(sb):
    rows = (sb.table("qianfan_usage").select("used").eq("day", _today()).limit(1).execute().data) or []
    return rows[0]["used"] if rows else 0


def budget_remaining(sb):
    return max(0, DAILY_CAP - budget_used(sb))


def budget_consume(sb, n=1):
    """读+增当日计数（T3 串行 workers=1 调用，read-modify-write 精确）。返回增后值。"""
    used = budget_used(sb) + n
    sb.table("qianfan_usage").upsert(
        {"day": _today(), "used": used, "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="day",
    ).execute()
    return used


def _first(row, *keys):
    for k in keys:
        v = str(row.get(k) or "").strip()
        if v:
            return v
    return ""


def _rows(data):
    if not isinstance(data, dict):
        return []
    for path in (("references",), ("results",), ("data", "references"), ("data", "results")):
        cur = data
        for p in path:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if isinstance(cur, list):
            return cur
    wp = ((data.get("webPages") or {}).get("value")) if isinstance(data.get("webPages"), dict) else None
    return wp if isinstance(wp, list) else []


def search(query, top_k=DEFAULT_TOP_K, client=None):
    """返回 [{title,url,snippet,publisher}]（publisher=域名）。禁用/缺 key/失败 → []。
    额度计数不在此（由调用方在实际发起一次调用后 budget_consume），以便先 budget_remaining 守门。"""
    if not is_configured():
        return []
    key = os.environ["BAIDU_QIANFAN_API_KEY"]
    body = {
        "messages": [{"role": "user", "content": str(query or "").strip()[:72]}],
        "search_source": "baidu_search_v2",
        "resource_type_filter": [{"type": "web", "top_k": top_k}],
        "search_recency_filter": "year",
    }
    headers = {"Authorization": f"Bearer {key}", "X-Appbuilder-Authorization": f"Bearer {key}",
               "Content-Type": "application/json", "Accept": "application/json"}
    own = client or httpx.Client()
    try:
        r = own.post(WEB_SEARCH_URL, json=body, headers=headers, timeout=TIMEOUT)
        if r.status_code >= 300:
            print(f"  [qf-err] HTTP {r.status_code}: {r.text[:160]}")
            return []
        data = r.json()
    except Exception as e:
        print(f"  [qf-err] {type(e).__name__}: {str(e)[:160]}")
        return []
    finally:
        if client is None:
            own.close()
    out = []
    for row in _rows(data):
        if not isinstance(row, dict):
            continue
        title = _first(row, "title", "web_anchor", "name")
        url = _first(row, "url", "link", "website")
        snip = _first(row, "snippet", "content", "summary", "description")
        if title and url:
            out.append({"title": title, "url": url, "snippet": snip,
                        "publisher": urlparse(url).netloc or "web"})
    if not out:  # 200 但无可用结果：打印响应形状，便于辨别鉴权/限流/响应结构问题
        keys = list(data.keys())[:6] if isinstance(data, dict) else type(data).__name__
        print(f"  [qf-empty] rows={len(_rows(data))} top_keys={keys} body={str(data)[:160]}")
    return out
