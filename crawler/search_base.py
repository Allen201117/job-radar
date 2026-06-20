"""多源搜索 provider 公共件：统一结果形状 + 域名提取。

统一结果形状（与 qianfan_search.search() 字节级一致 → 直接喂 insight_engine 的 sources）：
  {title, url, snippet, text, publisher}
- text     = 喂给 writer/judge 的正文（必填，下游读它做抽取+核对）；缺省回落 snippet
- publisher = 站点名或域名（共识门按不同 publisher 计数）
"""
from urllib.parse import urlparse


def domain_of(url):
    """取 url 域名（去 scheme / www）；空 url → 'web'。"""
    netloc = urlparse(str(url or "").strip()).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or "web"


def make_result(title, url, snippet="", text="", publisher=""):
    """组装统一结果。title/url 由调用方保证非空；text 缺省回落 snippet，publisher 缺省回落域名。"""
    url = str(url or "").strip()
    snippet = str(snippet or "").strip()
    return {
        "title": str(title or "").strip(),
        "url": url,
        "snippet": snippet,
        "text": (str(text or "").strip() or snippet),
        "publisher": (str(publisher or "").strip() or domain_of(url)),
    }
