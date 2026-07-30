import base64
import hashlib
import unittest

from logo_util import (
    COMPANY_DOMAIN_OVERRIDES,
    build_data_uri,
    candidate_domains,
    company_core_names,
    domain_for_company,
    icon_link_urls,
    icon_score,
    image_width,
    is_image_bytes,
    is_placeholder,
    is_platform_domain,
    normalize_mime,
    page_verifies_company,
    placeholder_probe_domains,
    platform_slug,
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

    def test_expanded_overrides_case_insensitive(self):
        # 扩充的 override + lower 归一：原名大小写 / 带英文变体、平台托管都命中官方域名
        self.assertEqual(domain_for_company("NVIDIA", "https://x.jobs.feishu.cn/p"), "nvidia.com")
        self.assertEqual(domain_for_company("科大讯飞", "https://x.jobs.feishu.cn/p"), "iflytek.com")
        self.assertEqual(
            domain_for_company("作业帮 Zuoyebang", "https://careers.mokahr.com/x"), "zuoyebang.com"
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


class PlatformSlugTests(unittest.TestCase):
    def test_subdomain_platforms(self):
        self.assertEqual(platform_slug("https://yangxiang.zhiye.com/campus"), "yangxiang")
        self.assertEqual(platform_slug("https://shengshu.jobs.feishu.cn/index/position"), "shengshu")
        self.assertEqual(
            platform_slug("https://manulife.wd3.myworkdayjobs.com/wday/cxs/manulife/MFCJH_Jobs/jobs"),
            "manulife",
        )

    def test_moka_path_slug(self):
        self.assertEqual(platform_slug("https://app.mokahr.com/social-recruitment/futu5/141927"), "futu5")
        self.assertEqual(platform_slug("https://app.mokahr.com/campus-recruitment/jimi"), "jimi")
        self.assertEqual(platform_slug("https://app-tc.mokahr.com/apply/wesure/6018"), "wesure")

    def test_ats_path_slug(self):
        self.assertEqual(
            platform_slug("https://api.smartrecruiters.com/v1/companies/expeditors/postings?limit=100"),
            "expeditors",
        )
        self.assertEqual(
            platform_slug("https://api.ashbyhq.com/posting-api/job-board/sierra?includeCompensation=true"),
            "sierra",
        )

    def test_rejects_generic_and_junk(self):
        self.assertIsNone(platform_slug("https://app.mokahr.com/"))
        self.assertIsNone(platform_slug("https://www.zhiye.com/campus"))
        self.assertIsNone(platform_slug(""))

    def test_candidate_domains_order(self):
        self.assertEqual(
            candidate_domains("yangxiang"), ["yangxiang.com", "yangxiang.cn", "yangxiang.com.cn"]
        )
        self.assertEqual(candidate_domains(""), [])


class CompanyCoreNamesTests(unittest.TestCase):
    def test_strips_org_suffix_and_region_prefix(self):
        self.assertIn("扬翔", company_core_names("扬翔股份有限公司"))
        self.assertIn("观安", company_core_names("上海观安信息技术股份有限公司"))

    def test_keeps_full_core_and_short_main(self):
        tokens = company_core_names("昂立教育")
        self.assertEqual(tokens[0], "昂立教育")
        self.assertIn("昂立", tokens)

    def test_mixed_zh_en(self):
        tokens = company_core_names("博乐科技 Bole Games")
        self.assertIn("博乐科技", tokens)
        self.assertIn("Bole Games", tokens)

    def test_drops_recruit_suffix_and_parens(self):
        self.assertIn("中国交建", company_core_names("中国交建 校招"))
        self.assertIn("米其林", company_core_names("米其林（中国）投资有限公司"))


class PageVerifyTests(unittest.TestCase):
    """核验门：正例用 live 抓到的真实首页标题；反例是 live 抓到的真实张冠李戴案例。"""

    def test_accepts_matching_pages(self):
        self.assertTrue(page_verifies_company("扬翔股份有限公司", "yangxiang", "扬翔股份"))
        self.assertTrue(page_verifies_company("昂立教育", "onlyedu", "上海昂立教育科技集团有限公司"))
        self.assertTrue(page_verifies_company("博乐科技 Bole Games", "bolegames", "北京博乐科技有限公司"))
        self.assertTrue(
            page_verifies_company("漱玉平民大药房连锁股份有限公司", "sypm", "漱玉平民大药房连锁股份有限公司")
        )
        self.assertTrue(page_verifies_company("阅文集团", "yuewen", "阅文集团_让好故事生生不息"))

    def test_rejects_wrong_company(self):
        # live 实测：轻松集团 slug=qsc → qsc.cn 实为美国音响公司 QSC，必须拒（张冠李戴红线）
        self.assertFalse(
            page_verifies_company("轻松集团", "qsc", "QSC | Audio, Video, and Control for Enhanced")
        )

    def test_rejects_unverifiable_page(self):
        # 域名也许确实是它的，但页面自证不了 → 保守拒（宁缺毋滥）
        self.assertFalse(page_verifies_company("蜂巢能源", "svolt", "Coming Soon"))
        self.assertFalse(page_verifies_company("扬翔股份有限公司", "yangxiang", ""))

    def test_english_company_matches_by_name_or_slug(self):
        self.assertTrue(page_verifies_company("Expeditors", "expeditors", "Expeditors International"))
        self.assertTrue(page_verifies_company("Meshy", "meshy", "Meshy - AI 3D Model Generator"))


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


class PlaceholderProbeDomainTests(unittest.TestCase):
    """icon.horse 占位图按域名首字符生成字母头像 → 指纹必须覆盖 a-z0-9，否则漏掉的字母会被当真 logo。"""

    def test_covers_all_letters_and_digits(self):
        doms = placeholder_probe_domains()
        self.assertEqual(len(doms), 36)
        self.assertEqual(len({d[0] for d in doms}), 36)
        for ch in ("a", "c", "s", "z", "0", "9"):
            self.assertTrue(any(d.startswith(ch) for d in doms), ch)

    def test_domains_are_implausible(self):
        for d in placeholder_probe_domains():
            self.assertIn("not-a-real-brand", d)
            self.assertTrue(d.endswith(".com"))


class SharedPlatformHostTests(unittest.TestCase):
    """共享平台域名必须被排除：否则同平台上百家公司会集体拿到平台自己的 logo（张冠李戴），
    且因为 domain 已「有值」，slug 兜底那条路不会被触发 = 白白放弃这些公司的真 logo。"""

    def test_late_added_platforms(self):
        # 2026-07-30 实测 sources 里的量：hotjob.cn 159 / iguopin.com 28 / oraclecloud.com 6 / eightfold.ai 4
        for d in ("hotjob.cn", "iguopin.com", "oraclecloud.com", "eightfold.ai"):
            self.assertTrue(is_platform_domain(d), d)

    def test_source_url_on_platform_yields_no_domain(self):
        self.assertIsNone(
            domain_for_company("奥迪汽车（中国）业务有限公司", "https://wecruit.hotjob.cn/SU123/pb/social.html", {})
        )
        self.assertIsNone(domain_for_company("某央企", "https://www.iguopin.com/job?company=x", {}))


class IsImageBytesTests(unittest.TestCase):
    def test_real_image_headers(self):
        self.assertTrue(is_image_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20))
        self.assertTrue(is_image_bytes(b"\x00\x00\x01\x00\x01\x00\x20"))
        self.assertTrue(is_image_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10))
        self.assertTrue(is_image_bytes(b"GIF89a" + b"\x00" * 10))
        self.assertTrue(is_image_bytes(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 4))

    def test_svg_with_and_without_xml_prolog(self):
        self.assertTrue(is_image_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"))
        self.assertTrue(is_image_bytes(b"  <?xml version='1.0'?><svg></svg>"))

    def test_rejects_html_error_page(self):
        # 站点 /favicon.ico 常返 200 + HTML（404 页面），必须挡掉，否则入库一张废图
        self.assertFalse(is_image_bytes(b"<!DOCTYPE html><html><head><title>404</title>"))
        self.assertFalse(is_image_bytes(b""))


class IconScoreTests(unittest.TestCase):
    def test_svg_ranks_high(self):
        self.assertEqual(icon_score("image/svg+xml", b"<svg></svg>"), 256)

    def test_png_uses_width(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + (180).to_bytes(4, "big") + b"\x00" * 8
        self.assertEqual(icon_score("image/png", png), 180)

    def test_unknown_scores_zero(self):
        self.assertEqual(icon_score("image/x-icon", b"\x00\x00\x01\x00"), 0)


class IconLinkUrlsTests(unittest.TestCase):
    def test_apple_touch_icon_first_and_favicon_fallback_last(self):
        html = (
            '<link rel="icon" href="/small.ico">'
            '<link rel="apple-touch-icon" href="/big-180.png">'
        )
        urls = icon_link_urls("https://example.com/", html)
        self.assertEqual(urls[0], "https://example.com/big-180.png")
        self.assertEqual(urls[1], "https://example.com/small.ico")
        self.assertEqual(urls[-1], "https://example.com/favicon.ico")

    def test_relative_protocol_and_absolute_hrefs(self):
        html = (
            '<link rel="shortcut icon" href="img/f.png">'
            '<link rel="icon" href="https://cdn.example.net/x.svg">'
        )
        urls = icon_link_urls("https://example.com/zh/", html)
        self.assertIn("https://example.com/zh/img/f.png", urls)
        self.assertIn("https://cdn.example.net/x.svg", urls)

    def test_skips_data_uri_and_dedupes(self):
        html = (
            '<link rel="icon" href="data:image/png;base64,AAA">'
            '<link rel="icon" href="/a.png"><link rel="icon" href="/a.png">'
        )
        urls = icon_link_urls("https://example.com/", html)
        self.assertNotIn("data:image/png;base64,AAA", urls)
        self.assertEqual(urls.count("https://example.com/a.png"), 1)

    def test_no_html_still_gives_favicon(self):
        self.assertEqual(icon_link_urls("https://example.com/", ""), ["https://example.com/favicon.ico"])

    def test_caps_candidates(self):
        html = "".join(f'<link rel="icon" href="/i{i}.png">' for i in range(20))
        self.assertLessEqual(len(icon_link_urls("https://example.com/", html)), 4)


class MustApplyBrandOverrideTests(unittest.TestCase):
    """必投清单品牌短名的域名覆盖：短名是校招专区展示名，配不上就只能首字母兜底。"""

    def test_short_brand_names_resolve(self):
        for name, domain in (
            ("美团", "meituan.com"),
            ("阿里巴巴", "alibabagroup.com"),
            ("招商银行", "cmbchina.com"),
            ("比亚迪", "byd.com"),
            ("顺丰", "sf-express.com"),
        ):
            self.assertEqual(domain_for_company(name, "", COMPANY_DOMAIN_OVERRIDES), domain)

    def test_live_verification_failures_stay_unmapped(self):
        # live 核验没过的（域名被抢注 / 已改名 / 根域是无关站）一律不收，宁缺毋滥
        for name in ("立讯精密", "光线传媒", "卓越教育", "中储智运", "万达电影"):
            self.assertIsNone(domain_for_company(name, "", COMPANY_DOMAIN_OVERRIDES), name)

    def test_no_platform_domain_leaked_into_overrides(self):
        # 唯一豁免：Workday 自己就是雇主，它的官网恰好也是我们排除的 ATS 平台域名。
        for name, domain in COMPANY_DOMAIN_OVERRIDES.items():
            if name == "workday":
                continue
            self.assertFalse(is_platform_domain(domain), f"{name} → {domain} 是招聘平台域名")


if __name__ == "__main__":
    unittest.main()
