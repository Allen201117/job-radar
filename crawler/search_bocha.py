"""博查 AI 搜索 provider 解析：POST https://api.bochaai.com/v1/web-search。

中文 UGC（知乎/小红书/公众号）覆盖最深。响应 data.webPages.value[]：
  {name,url,snippet,summary,siteName,datePublished}
"""
import search_base


def _rows(data):
    if not isinstance(data, dict):
        return []
    for container in ((data.get("data") or {}), data):
        wp = container.get("webPages") if isinstance(container, dict) else None
        val = wp.get("value") if isinstance(wp, dict) else None
        if isinstance(val, list):
            return val
    return []


def parse_response(data):
    """博查 JSON → [{title,url,snippet,text,publisher}]。纯函数，无网络。"""
    out = []
    for row in _rows(data):
        if not isinstance(row, dict):
            continue
        title = row.get("name") or row.get("title")
        url = row.get("url")
        if not (str(title or "").strip() and str(url or "").strip()):
            continue
        snippet = row.get("snippet") or ""
        text = row.get("summary") or snippet  # summary 更长 → 优先作 LLM 正文
        out.append(search_base.make_result(title, url, snippet, text, row.get("siteName")))
    return out


def build_request(key, query, top_k):
    """(url, headers, json_body)。summary=True 让博查回长摘要作 LLM 正文；freshness 收近一年。"""
    return (
        "https://api.bochaai.com/v1/web-search",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        {"query": str(query or "").strip()[:100], "count": top_k,
         "summary": True, "freshness": "oneYear"},
    )
