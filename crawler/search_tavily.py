"""Tavily 搜索 provider 解析：POST https://api.tavily.com/search。

返回已清洗 content，最贴合喂 LLM。响应 results[]：{title,url,content,raw_content,score}。
"""
import search_base


def parse_response(data):
    """Tavily JSON → [{title,url,snippet,text,publisher}]。纯函数，无网络。"""
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
        content = row.get("content") or ""  # content 已是相关片段；snippet=text 同源
        out.append(search_base.make_result(title, url, content, content))
    return out


def build_request(key, query, top_k):
    """(url, headers, json_body)。Tavily 把 api_key 放 body；basic 深度省额度。"""
    return (
        "https://api.tavily.com/search",
        {"Content-Type": "application/json"},
        {"api_key": key, "query": str(query or "").strip()[:400], "max_results": top_k,
         "search_depth": "basic", "topic": "general"},
    )
