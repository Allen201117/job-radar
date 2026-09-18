"""通用 HTTP 搜索 provider：封装 key/熔断/每日预算 + 一次 httpx 调用 + 注入式 build_request/parse。

具体源（bocha/tavily/serper）只提供纯函数 build_request 与 parse_response；HTTP/预算/兜底在此统一。
缺 key / 被熔断 / HTTP 错 / 网络异常一律静默返回 []（router 会跳到下一源）。
"""
import os

import httpx

import search_budget
from search_router import SearchAccountError, is_search_account_error


class HttpSearchProvider:
    def __init__(self, name, key_env, parse, build_request, cap_env, default_cap,
                 disabled_env=None, timeout=12, method="POST"):
        # method="GET" 时 build_request 的第三项当**查询串参数**发（Brave 只支持 GET，
        # 给它发 POST 直接 405）；POST 时当 JSON body 发，与 tavily/serper/bocha 一致。
        self.method = str(method or "POST").upper()
        self.name = name
        self.key_env = key_env
        self.parse = parse
        self.build_request = build_request
        self.cap_env = cap_env
        self.default_cap = default_cap
        self.disabled_env = disabled_env or f"{name.upper()}_SEARCH_DISABLED"
        self.timeout = timeout

    def _disabled(self):
        return str(os.environ.get(self.disabled_env, "")).strip().lower() in ("1", "true", "yes")

    def is_configured(self):
        return bool(os.environ.get(self.key_env)) and not self._disabled()

    def cap(self):
        try:
            return int(os.environ.get(self.cap_env, str(self.default_cap)))
        except (TypeError, ValueError):
            return self.default_cap

    def remaining(self, sb):
        return search_budget.remaining(sb, self.name, self.cap())

    def consume(self, sb, n=1):
        search_budget.consume(sb, self.name, n)

    def search(self, query, top_k=8, client=None):
        if not self.is_configured():
            return []
        url, headers, body = self.build_request(os.environ[self.key_env], query, top_k)
        own = client or httpx.Client()
        try:
            if self.method == "GET":
                r = own.get(url, params=body, headers=headers, timeout=self.timeout)
            else:
                r = own.post(url, json=body, headers=headers, timeout=self.timeout)
            if is_search_account_error(r.status_code, r.text):
                raise SearchAccountError(f"HTTP {r.status_code}: {r.text[:160]}")
            if r.status_code >= 300:
                print(f"  [{self.name}-err] HTTP {r.status_code}: {r.text[:160]}")
                return []
            data = r.json()
        except SearchAccountError:
            raise
        except Exception as e:
            print(f"  [{self.name}-err] {type(e).__name__}: {str(e)[:160]}")
            return []
        finally:
            if client is None:
                own.close()
        return self.parse(data)
