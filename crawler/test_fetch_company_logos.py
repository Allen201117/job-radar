"""fetch_company_logos 的三源取图逻辑单测（不打真实网络，用 stub client）。

重点钉住两条踩过的坑：
1. icon.horse 的占位图是按域名首字符生成的灰底字母块 → 没拿到该字符的指纹时**绝不能用它**；
2. 三源要取「最清晰」的那张，且都必须过图片内容嗅探门（站点 /favicon.ico 常返 HTML）。
"""
import unittest

import fetch_company_logos as F

PNG_16 = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (16).to_bytes(4, "big") + b"\x00" * 8
PNG_180 = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (180).to_bytes(4, "big") + b"\x00" * 8
PNG_256_FAKE = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (256).to_bytes(4, "big") + b"\x00" * 9
HTML = b"<!DOCTYPE html><html><head><title>404</title></head></html>"


class Resp:
    def __init__(self, status=200, content=b"", ctype="image/png", url="https://x.test/", text=""):
        self.status_code = status
        self.content = content
        self.headers = {"content-type": ctype}
        self.url = url
        self.text = text


class StubClient:
    """按 URL 前缀返回预设响应；未匹配的返回 404。记录请求过的 URL 便于断言。"""

    def __init__(self, routes):
        self.routes = routes
        self.seen = []

    def get(self, url, timeout=None):
        self.seen.append(url)
        # 最长前缀优先，否则 "https://a.test" 会把 "https://a.test/icon.png" 也吞掉
        for prefix in sorted(self.routes, key=len, reverse=True):
            resp = self.routes[prefix]
            if url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return Resp(status=404)


class IconHorseGateTests(unittest.TestCase):
    """icon.horse 只在「拿到该首字符占位指纹」且「图不等于指纹」时才可用。"""

    def _client(self, ih_content):
        return StubClient({
            "https://icons.duckduckgo.com": Resp(status=404),
            "https://acme.test": Resp(status=500),          # 官网打不开
            "https://www.acme.test": Resp(status=500),
            "https://icon.horse/icon/acme.test": Resp(content=ih_content),
        })

    def test_skipped_when_fingerprint_for_char_missing(self):
        # 缺 'a' 的指纹 → 宁缺毋滥，直接不用 icon.horse（哪怕它返回了图）
        c = self._client(PNG_180)
        self.assertIsNone(F.fetch_one(c, "acme.test", {"b": "whatever"}))
        self.assertFalse(any("icon.horse" in u for u in c.seen), "缺指纹时不该请求 icon.horse")

    def test_rejected_when_image_equals_placeholder_fingerprint(self):
        import hashlib

        fp = hashlib.md5(PNG_256_FAKE).hexdigest()
        c = self._client(PNG_256_FAKE)
        self.assertIsNone(F.fetch_one(c, "acme.test", {"a": fp}))

    def test_accepted_when_image_differs_from_fingerprint(self):
        import hashlib

        fp = hashlib.md5(PNG_256_FAKE).hexdigest()
        c = self._client(PNG_180)
        got = F.fetch_one(c, "acme.test", {"a": fp})
        self.assertIsNotNone(got)
        self.assertEqual(got["source"], "iconhorse")


class SourcePriorityTests(unittest.TestCase):
    def test_site_icon_wins_over_small_duckduckgo(self):
        c = StubClient({
            "https://icons.duckduckgo.com": Resp(content=PNG_16, ctype="image/x-icon"),
            "https://acme.test": Resp(
                content=b"", text='<link rel="apple-touch-icon" href="/big.png">', url="https://acme.test/"
            ),
            "https://acme.test/big.png": Resp(content=PNG_180),
        })
        got = F.fetch_one(c, "acme.test", {})
        self.assertEqual(got["source"], "site")
        self.assertEqual(got["width"], 180)

    def test_large_duckduckgo_skips_site_fetch(self):
        c = StubClient({"https://icons.duckduckgo.com": Resp(content=PNG_180)})
        got = F.fetch_one(c, "acme.test", {})
        self.assertEqual(got["source"], "duckduckgo")
        self.assertFalse(any(u.startswith("https://acme.test") for u in c.seen), "已够清晰就不该再抓官网")

    def test_html_error_page_at_favicon_is_rejected(self):
        # 站点 /favicon.ico 返 200 + HTML 是常态，必须被内容嗅探挡掉，否则入库一张废图
        c = StubClient({
            "https://icons.duckduckgo.com": Resp(status=404),
            "https://acme.test": Resp(content=b"", text="<html></html>", url="https://acme.test/"),
            "https://acme.test/favicon.ico": Resp(content=HTML, ctype="text/html"),
        })
        self.assertIsNone(F.fetch_one(c, "acme.test", {}))

    def test_oversized_image_rejected(self):
        c = StubClient({"https://icons.duckduckgo.com": Resp(content=PNG_180 + b"\x00" * 300_000)})
        self.assertIsNone(F.fetch_one(c, "acme.test", {}))


class SiteIconTests(unittest.TestCase):
    def test_falls_back_to_www_when_bare_domain_fails(self):
        c = StubClient({
            "https://acme.test": Resp(status=502),
            "https://www.acme.test": Resp(
                content=b"", text='<link rel="icon" href="/f.png">', url="https://www.acme.test/"
            ),
            "https://www.acme.test/f.png": Resp(content=PNG_180),
        })
        got = F.fetch_site_icon(c, "acme.test")
        self.assertIsNotNone(got)
        self.assertEqual(got["width"], 180)

    def test_connection_error_is_swallowed(self):
        c = StubClient({"https://acme.test": RuntimeError("boom"), "https://www.acme.test": RuntimeError("boom")})
        self.assertIsNone(F.fetch_site_icon(c, "acme.test"))


if __name__ == "__main__":
    unittest.main()
