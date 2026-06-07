import unittest

import normalizer
from adapters.base import RawJob


class JobQualityTests(unittest.TestCase):
    def test_normalizes_china_city_aliases(self):
        self.assertEqual(normalizer.clean_location("北京市"), "北京")
        self.assertEqual(normalizer.clean_location("Shanghai"), "上海")
        self.assertEqual(normalizer.clean_location("全国多地"), "全国")

    def test_extracts_china_job_type_rules(self):
        self.assertEqual(normalizer.extract_job_type("暑期实习-数据分析"), "暑期实习")
        self.assertEqual(normalizer.extract_job_type("管理培训生", "graduate program"), "管培生")
        self.assertEqual(normalizer.extract_job_type("投研研究员", "行业研究"), "研究岗")

    def test_accepts_real_apple_detail_url(self):
        job = RawJob(
            company="Apple",
            title="Software Engineer, Watch Software",
            location="Cupertino",
            jd_url="https://jobs.apple.com/en-us/details/200609884-0836/software-engineer-watch-software?team=SFTWR",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://jobs.apple.com/en-us/search"
        )

        self.assertTrue(ok, reason)

    def test_rejects_homepage_as_job_detail(self):
        job = RawJob(
            company="京东",
            title="首 页",
            jd_url="https://zhaopin.jd.com/",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://zhaopin.jd.com/web/job/job_info_list/3"
        )

        self.assertFalse(ok)
        self.assertIn("navigation", reason)

    def test_rejects_source_search_page_as_job_detail(self):
        job = RawJob(
            company="海尔",
            title="全部岗位",
            jd_url="https://maker.haier.net/client/job/index",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://maker.haier.net/client/job/index"
        )

        self.assertFalse(ok)
        self.assertIn("source url", reason)

    def test_rejects_recruiting_campaign_page_as_job_detail(self):
        job = RawJob(
            company="海尔",
            title="科技人才招聘",
            jd_url="https://maker.haier.net/client/techtalent/index.html",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://maker.haier.net/client/job/index"
        )

        self.assertFalse(ok)
        self.assertIn("navigation", reason)

    def test_rejects_language_redirect_as_job_detail(self):
        job = RawJob(
            company="Siemens",
            title="English",
            jd_url="https://jobs.siemens.com/en_US/externaljobs/redirect",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://jobs.siemens.com/careers/search"
        )

        self.assertFalse(ok)
        self.assertIn("navigation", reason)

    def test_rejects_siemens_recruitment_category_as_job_detail(self):
        job = RawJob(
            company="Siemens",
            title="PROFESSIONAL",
            jd_url="https://jobs.siemens.com/siemens/position/index?recruitmentType=SOCIALRECRUITMENT",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://jobs.siemens.com.cn/siemens/position/index"
        )

        self.assertFalse(ok)
        self.assertIn("navigation", reason)


class StructuredFieldExtractionTests(unittest.TestCase):
    """经验/学历/截止 从完整 JD 抽取（#1），抽不到返回 None。"""

    def test_experience_chinese(self):
        self.assertEqual(normalizer.extract_experience("要求3-5年相关工作经验"), "3-5年")
        self.assertEqual(normalizer.extract_experience("5年以上工作经验"), "5年+")
        self.assertEqual(normalizer.extract_experience("面向2026届应届毕业生"), "应届/不限")
        self.assertEqual(normalizer.extract_experience("经验不限，欢迎投递"), "应届/不限")

    def test_experience_english(self):
        self.assertEqual(normalizer.extract_experience("3-5 years of experience required"), "3-5年")
        self.assertEqual(normalizer.extract_experience("5+ years experience"), "5年+")
        self.assertIsNone(normalizer.extract_experience("We build great products"))

    def test_experience_strips_html(self):
        self.assertEqual(normalizer.extract_experience("<p>至少 <b>3</b> 年经验</p>"), "3年+")

    def test_education(self):
        self.assertEqual(normalizer.extract_education("博士学历优先"), "博士")
        self.assertEqual(normalizer.extract_education("硕士及以上"), "硕士")
        self.assertEqual(normalizer.extract_education("本科及以上学历"), "本科")
        self.assertEqual(normalizer.extract_education("Bachelor degree required"), "本科")
        self.assertEqual(normalizer.extract_education("学历不限"), "不限")
        self.assertIsNone(normalizer.extract_education("强沟通能力"))

    def test_education_priority_phd_over_bachelor(self):
        # 同时出现时取最高学历（博士先判定）
        self.assertEqual(normalizer.extract_education("本科起，博士优先"), "博士")

    def test_deadline(self):
        self.assertEqual(normalizer.extract_deadline("申请截止2026-06-30"), "2026-06-30")
        self.assertEqual(normalizer.extract_deadline("投递截止：2026年6月30日"), "2026-6-30")
        self.assertEqual(normalizer.extract_deadline("长期有效，欢迎随时投递"), "长期有效")
        self.assertEqual(normalizer.extract_deadline("rolling basis"), "长期有效")
        self.assertIsNone(normalizer.extract_deadline("岗位职责：写代码"))

    def test_all_none_on_empty(self):
        for fn in (normalizer.extract_experience, normalizer.extract_education, normalizer.extract_deadline):
            self.assertIsNone(fn(None))
            self.assertIsNone(fn(""))


class CleanSummaryTest(unittest.TestCase):
    def test_decodes_entities_then_strips_tags(self):
        # greenhouse content 是实体编码 HTML：不解码会原样显示 &lt;p&gt; 乱码
        self.assertEqual(normalizer.clean_summary("&lt;p&gt;-&lt;/p&gt;"), "-")
        out = normalizer.clean_summary(
            '&lt;div class=&quot;intro&quot;&gt;&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;Hello world&lt;/p&gt;')
        self.assertNotIn("&lt;", out)
        self.assertNotIn("<", out)
        self.assertIn("About", out)
        self.assertIn("Hello world", out)

    def test_plain_and_real_tags(self):
        self.assertEqual(normalizer.clean_summary("plain text stays"), "plain text stays")
        self.assertEqual(normalizer.clean_summary("<p>hi</p>"), "hi")

    def test_none(self):
        self.assertIsNone(normalizer.clean_summary(None))


class IsChinaLocationTests(unittest.TestCase):
    def test_real_china_locations(self):
        for loc in ("Shanghai, China", "China, Beijing", "广东·深圳市", "Hong Kong",
                    "Macau", "Suzhou", "Xi'an", "China - Remote", "Greater China"):
            self.assertTrue(normalizer.is_china_location(loc), loc)

    def test_comma_and_hyphen_split_hong_kong(self):
        # Workday externalPath 把 'Hong-Kong' 拆成 'Hong, Kong'/'Hong Kong'，逗号/连字符不应破坏识别
        for loc in ("Hong, Kong", "Hong-Kong", "Asia, Pacific, Hong, Kong, Mongkok",
                    "Asia-Pacific-China-Beijing"):
            self.assertTrue(normalizer.is_china_location(loc), loc)

    def test_substring_false_positives_excluded(self):
        # 'macao'(澳门) 不应命中 'Humacao'（波多黎各）；非华地点一律 False
        for loc in ("USA, PR, Humacao", "Mumbai, India", "Remote - Delhi",
                    "New York, United States", "London, UK", "Singapore"):
            self.assertFalse(normalizer.is_china_location(loc), loc)

    def test_empty(self):
        self.assertFalse(normalizer.is_china_location(None))
        self.assertFalse(normalizer.is_china_location(""))


if __name__ == "__main__":
    unittest.main()
