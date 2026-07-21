import base64
import hashlib
import unittest

from logo_util import (
    COMPANY_DOMAIN_OVERRIDES,
    build_data_uri,
    domain_for_company,
    image_width,
    is_placeholder,
    is_platform_domain,
    normalize_mime,
    registrable_domain,
)


class RegistrableDomainTests(unittest.TestCase):
    def test_strips_subdomain(self):
        self.assertEqual(registrable_domain("talent.baidu.com"), "baidu.com")
        self.assertEqual(registrable_domain("nio.jobs.feishu.cn"), "feishu.cn")
        self.assertEqual(registrable_domain("careers.tencent.com"), "tencent.com")

    def test_multi_level_suffix(self):
        self.assertEqual(registrable_domain("hr.example.com.cn"), "example.com.cn")

    def test_port_and_scheme_noise(self):
        self.assertEqual(registrable_domain("jobs.foo.com:443"), "foo.com")

    def test_bare_and_empty(self):
        self.assertEqual(registrable_domain("foo.com"), "foo.com")
        self.assertEqual(registrable_domain(""), "")


class PlatformDomainTests(unittest.TestCase):
    def test_known_platforms(self):
        for d in ("feishu.cn", "mokahr.com", "greenhouse.io", "lever.co", "workday.com"):
            self.assertTrue(is_platform_domain(d), d)

    def test_substring_platforms(self):
        self.assertTrue(is_platform_domain("xxx.beisen.com"))
        self.assertTrue(is_platform_domain("italent.cn"))

    def test_real_company_not_platform(self):
        for d in ("baidu.com", "tencent.com", "nio.com"):
            self.assertFalse(is_platform_domain(d), d)


class DomainForCompanyTests(unittest.TestCase):
    def test_override_wins(self):
        # 小米 source 在 mioffice.cn（平台）→ 覆盖表兜底 mi.com
        self.assertEqual(
            domain_for_company("小米", "https://xiaomi.jobs.f.mioffice.cn/index/position"),
            "mi.com",
        )
        self.assertEqual(
            domain_for_company("蔚来", "https://nio.jobs.feishu.cn/index/position"),
            "nio.com",
        )

    def test_non_platform_host(self):
        self.assertEqual(
            domain_for_company("百度", "https://talent.baidu.com/jobs/list"),
            "baidu.com",
        )

    def test_greenhouse_slug(self):
        self.assertEqual(
            domain_for_company("Airbnb", "https://boards-api.greenhouse.io/v1/boards/airbnb/jobs"),
            "airbnb.com",
        )

    def test_lever_slug(self):
        self.assertEqual(
            domain_for_company("Binance", "https://api.lever.co/v0/postings/binance"),
            "binance.com",
        )

    def test_platform_without_override_or_slug(self):
        # 飞书托管但覆盖表没有、又不是 greenhouse/lever → None（前端首字母兜底）
        self.assertIsNone(
            domain_for_company("某未知公司", "https://unknown.jobs.feishu.cn/index/position"),
        )


class PlaceholderTests(unittest.TestCase):
    def test_hit_and_miss(self):
        img = b"fake-placeholder-bytes"
        fp = {hashlib.md5(img).hexdigest()}
        self.assertTrue(is_placeholder(img, fp))
        self.assertFalse(is_placeholder(b"a-real-different-logo", fp))

    def test_empty_is_placeholder(self):
        self.assertTrue(is_placeholder(b"", set()))


class DataUriTests(unittest.TestCase):
    def test_png(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
        uri = build_data_uri("image/png", png)
        self.assertTrue(uri.startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(uri.split(",", 1)[1]), png)

    def test_ico_mime_normalization(self):
        ico = b"\x00\x00\x01\x00" + b"\x00" * 10
        self.assertTrue(build_data_uri("image/vnd.microsoft.icon", ico).startswith("data:image/x-icon;base64,"))

    def test_svg(self):
        svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        self.assertTrue(build_data_uri("image/svg+xml", svg).startswith("data:image/svg+xml;base64,"))

    def test_sniff_when_content_type_missing(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
        self.assertEqual(normalize_mime(None, png), "image/png")


class ImageWidthTests(unittest.TestCase):
    def test_png_width(self):
        # PNG 头 8B + IHDR 长度(4)+"IHDR"(4)+width(4)=256 ...
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (256).to_bytes(4, "big") + b"\x00" * 8
        self.assertEqual(image_width(png), 256)

    def test_ico_width(self):
        ico = b"\x00\x00\x01\x00\x01\x00" + b"\x20"  # 第 7 字节 width=32
        self.assertEqual(image_width(ico), 32)

    def test_ico_width_zero_means_256(self):
        ico = b"\x00\x00\x01\x00\x01\x00" + b"\x00"
        self.assertEqual(image_width(ico), 256)

    def test_unknown_returns_none(self):
        self.assertIsNone(image_width(b"not-an-image"))


if __name__ == "__main__":
    unittest.main()
