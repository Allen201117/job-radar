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


class IconHorseDisabledTests(unittest.TestCase):
    """icon.horse 已停用：两源都拿不到就返回 None（前端首字母兜底），绝不再去请求它。

    停用理由见 fetch_company_logos 文件头——占位指纹补全后它的真图产出是 0，
    留着只会往库里塞灰底通用字母块。
    """

    def _client(self, ih_content=PNG_180):
        return StubClient({
            "https://icons.duckduckgo.com": Resp(status=404),
            "https://acme.test": Resp(status=500),          # 官网打不开
            "https://www.acme.test": Resp(status=500),
            "https://icon.horse/icon/acme.test": Resp(content=ih_content),
        })

    def test_never_requests_icon_horse(self):
        import hashlib

        c = self._client()
        # 即使给了完整指纹、即使 icon.horse 会返回一张「不是占位图」的图，也不该用它
        self.assertIsNone(F.fetch_one(c, "acme.test", {"a": hashlib.md5(PNG_256_FAKE).hexdigest()}))
        self.assertFalse(any("icon.horse" in u for u in c.seen), "不该再请求 icon.horse")

    def test_returns_none_without_fingerprints(self):
        self.assertIsNone(F.fetch_one(self._client(), "acme.test", {}))


class FakeLogoDetectionTests(unittest.TestCase):
    """find_fake_logo_keys 三条判据。判据 3 是 live 踩出来的：10 家公司 domain=iguopin.com
    全显示成「国聘」的 logo，而判据 2（跨域名重复）抓不到——它们共用同一个错域名。"""

    class FakeSB:
        def __init__(self, rows):
            self._rows = rows

        def table(self, _name):
            return self

        def select(self, _cols):
            return self

        def eq(self, *_a):
            return self

        def execute(self):
            return type("R", (), {"data": self._rows})()

    @staticmethod
    def _row(key, domain, payload):
        import base64

        return {
            "company_key": key,
            "domain": domain,
            "logo_data": "data:image/png;base64," + base64.b64encode(payload).decode(),
        }

    def test_platform_domain_is_fake_even_without_duplicate(self):
        sb = self.FakeSB([self._row("奔驰", "iguopin.com", b"unique-image-1")])
        self.assertEqual(F.find_fake_logo_keys(sb, {}), {"奔驰"})

    def test_workday_the_employer_is_exempt(self):
        # 公司自己就是平台时，覆盖表里它的域名正好等于该平台域名 → 不算假
        sb = self.FakeSB([self._row("workday", "workday.com", b"real-workday-logo")])
        self.assertEqual(F.find_fake_logo_keys(sb, {}), set())

    def test_same_image_across_two_domains_is_fake(self):
        sb = self.FakeSB([
            self._row("a", "a.com", b"same-bytes"),
            self._row("b", "b.com", b"same-bytes"),
        ])
        self.assertEqual(F.find_fake_logo_keys(sb, {}), {"a", "b"})

    def test_same_image_same_domain_is_not_fake(self):
        # 同品牌两个名字变体共用一个域名 → 图当然一样，不能误杀
        sb = self.FakeSB([
            self._row("美团", "meituan.com", b"same-bytes"),
            self._row("美团 meituan", "meituan.com", b"same-bytes"),
        ])
        self.assertEqual(F.find_fake_logo_keys(sb, {}), set())

    def test_placeholder_fingerprint_hit_is_fake(self):
        import hashlib

        payload = b"letter-avatar-bytes"
        sb = self.FakeSB([self._row("某公司", "acme.test", payload)])
        fp = {"a": hashlib.md5(payload).hexdigest()}
        self.assertEqual(F.find_fake_logo_keys(sb, fp), {"某公司"})


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
