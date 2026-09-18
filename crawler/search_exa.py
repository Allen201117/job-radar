"""Exa（exa.ai）搜索 provider 解析：POST https://api.exa.ai/search。

为何加它（2026-09-18）：注册送 $10 ≈ 1,000 次，**不绑卡**。但它是**一次性额度**（与 serper
同性质、用完就没），所以日顶砍到 15、排在按周期回血的源之后 —— 顺序口径见 default_router
的注释「每天/每月回血 → 一次性 → 付费」。

响应形状 `{"results": [{"title","url","text",...}]}`；`type:"auto"` 让 Exa 自己在
神经检索与关键词检索之间选（查「XX 校园招聘 官网」这类导航型查询时关键词检索更准）。
"""
import search_base


def parse_response(data):
    """Exa JSON → [{title,url,snippet,text,publisher}]。纯函数，无网络。"""
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        return []
    out = []
    for row in data["results"]:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        url = row.get("url")
        if not (str(title or "").strip() and str(url or "").strip()):
            continue
        # text 可能是整页正文（很长）；snippet 截断供展示，text 原样留给下游 LLM。
        text = str(row.get("text") or row.get("summary") or "")
        out.append(search_base.make_result(title, url, text[:600], text))
    return out


def build_request(key, query, top_k):
    """(url, headers, json_body)。key 走 x-api-key 头；startPublishedDate 限近 RECENCY_YEARS 年。"""
    return (
        "https://api.exa.ai/search",
        {"x-api-key": key, "Content-Type": "application/json"},
        {"query": str(query or "").strip()[:400],
         "numResults": max(1, min(25, int(top_k or 8))),
         "type": "auto",
         "startPublishedDate": search_base.recency_start_iso()},
    )
