"""把现有 qianfan_search 包装成 router 的一个 provider：复用其 qianfan_usage 预算与 50/日硬顶，
行为与单用千帆时完全一致（向后兼容）。
"""
import qianfan_search as qf


class QianfanProvider:
    name = "qianfan"

    def is_configured(self):
        return qf.is_configured()

    def remaining(self, sb):
        return qf.budget_remaining(sb)

    def search(self, query, top_k=qf.DEFAULT_TOP_K, client=None):
        return qf.search(query, top_k=top_k, client=client)

    def consume(self, sb, n=1):
        qf.budget_consume(sb, n)
