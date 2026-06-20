"""Serper 谷歌 SERP provider 解析：POST https://google.serper.dev/search。

全球兜底（国内公司谷歌也有索引）。响应 organic[]：{title,link,snippet,position,date}。
"""
import search_base


def parse_response(data):
    """Serper JSON → [{title,url,snippet,text,publisher}]。纯函数，无网络。"""
    if not isinstance(data, dict) or not isinstance(data.get("organic"), list):
        return []
    out = []
    for row in data["organic"]:
        if not isinstance(row, dict):
            continue
        title = row.get("title")
        url = row.get("link")
        if not (str(title or "").strip() and str(url or "").strip()):
            continue
        snippet = row.get("snippet") or ""
        out.append(search_base.make_result(title, url, snippet, snippet))
    return out


def build_request(key, query, top_k):
    """(url, headers, json_body)。Serper 把 key 放 X-API-KEY 头；gl/hl 收中文区；
    tbs 自定义日期窗限近 RECENCY_YEARS 年（保即时性）。"""
    tbs = f"cdr:1,cd_min:{search_base.recency_start_us()},cd_max:{search_base.recency_start_us(0)}"
    return (
        "https://google.serper.dev/search",
        {"X-API-KEY": key, "Content-Type": "application/json"},
        {"q": str(query or "").strip(), "num": top_k, "gl": "cn", "hl": "zh-cn", "tbs": tbs},
    )
