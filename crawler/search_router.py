"""多源搜索路由器：按配置取已启用 provider，逐个在各自每日预算内检索，并取去重，单源报错兜底跳过。

设计：替换 insight_backlog 里对单一 qianfan 的直连——输出形状不变（{title,url,snippet,text,publisher}），
下游 insight_engine.run_pipeline 零改动。多源并取天然喂饱「≥2 不同 publisher」共识门。

provider 协议（见 search_provider_http.SearchProvider / search_qianfan.QianfanProvider）：
  name / is_configured() / remaining(sb) -> int / search(query, top_k, client) -> list / consume(sb, n)
"""


class SearchRouter:
    def __init__(self, providers):
        self.providers = list(providers or [])

    def _active(self):
        return [p for p in self.providers if p.is_configured()]

    def is_configured(self):
        """任一 provider 配置了 key 即可用。"""
        return any(p.is_configured() for p in self.providers)

    def remaining(self, sb):
        """已配置 provider 当日剩余额度之和（drain 用它判断是否还能跑）。"""
        return sum(p.remaining(sb) for p in self._active())

    def search(self, sb, query, top_k=8, client=None):
        """各已配置且有额度的 provider 依次检索 → 按 url 并取去重（保留先出现者）。
        单源报错/无结果不影响其它源；返回统一形状列表。"""
        out, seen = [], set()
        for p in self._active():
            try:
                if p.remaining(sb) <= 0:
                    continue
                results = p.search(query, top_k, client) or []
                p.consume(sb, 1)  # 实际发起一次检索 → 记一次额度（无论结果多少）
            except Exception as e:
                print(f"  [search-router] {getattr(p, 'name', '?')} 兜底跳过: "
                      f"{type(e).__name__}: {str(e)[:120]}")
                continue
            for r in results:
                url = (r or {}).get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append(r)
        return out


def default_router():
    """按环境变量装配默认多源路由器（顺序=中文深度优先：博查 → Tavily → Serper → 千帆）。
    未配 key 的源 router 自会跳过 → 「先用各家免费额度验证灵活性」即配哪个用哪个。
    每源日顶默认值仅为安全上限，正式放量由 *_DAILY_CAP env 按月度预算调。"""
    import search_bocha
    import search_qianfan
    import search_serper
    import search_tavily
    from search_provider_http import HttpSearchProvider

    return SearchRouter([
        HttpSearchProvider("bocha", "BOCHA_API_KEY", search_bocha.parse_response,
                           search_bocha.build_request, "BOCHA_DAILY_CAP", 200),
        HttpSearchProvider("tavily", "TAVILY_API_KEY", search_tavily.parse_response,
                           search_tavily.build_request, "TAVILY_DAILY_CAP", 300),
        HttpSearchProvider("serper", "SERPER_API_KEY", search_serper.parse_response,
                           search_serper.build_request, "SERPER_DAILY_CAP", 200),
        search_qianfan.QianfanProvider(),
    ])
