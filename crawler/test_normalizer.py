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

    def test_job_type_drops_weak_campus_words(self):
        # 弱词 graduate(=硕士学历) / campus(=办公园区) 不再误判校招（社招岗被误标校招的写入端源头）
        self.assertIsNone(normalizer.extract_job_type("Software Engineer", "requires a graduate degree"))
        self.assertIsNone(normalizer.extract_job_type("Sales Manager", "based at our Shanghai campus"))
        # 真校招强标记仍判得出
        self.assertEqual(normalizer.extract_job_type("2026校园招聘-算法"), "校招")
        self.assertEqual(normalizer.extract_job_type("Software Engineer", "open to new grad"), "校招")

    def test_is_recruitment_type_gates_adapter_jobtype(self):
        # 真招聘类型 → True（run.py 信任 adapter 直填，不被正文推断覆盖）
        for v in ("社会招聘", "社招", "校招", "校园招聘", "应届生", "实习", "实习生", "管培生", "留学生专项"):
            self.assertTrue(normalizer.is_recruitment_type(v), v)
        # 职能/类别名 / 空 / 用工模式 → False（退回正文推断）
        for v in ("研发", "业务类", "工程管理序列", "技术", "全职", "兼职", "", None):
            self.assertFalse(normalizer.is_recruitment_type(v), repr(v))

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

    def test_accepts_spa_hash_route_job_detail(self):
        # 携程等纯 hash 路由 SPA：domain/#/...，path 为空(→'/')但真实岗位在 fragment。
        # 质量门用 fragment 当有效路径，不得误判为首页。
        job = RawJob(
            company="携程",
            title="服务产品经理",
            jd_url="https://careers.ctrip.com/#/experienced/job-detail/MJ035500",
        )

        ok, reason = normalizer.validate_job_quality(job, "https://careers.ctrip.com/")

        self.assertTrue(ok, reason)

    def test_rejects_spa_hash_homepage(self):
        # hash 首页/导航(#/home、#/searchJobs)即使 path='/' 也必须拦截。
        for frag in ("#/home", "#/searchJobs"):
            job = RawJob(
                company="携程",
                title="工程师",
                jd_url=f"https://careers.ctrip.com/{frag}",
            )
            ok, reason = normalizer.validate_job_quality(job, "https://x.com/")
            self.assertFalse(ok, f"{frag} 应被拦")
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

    def test_accepts_workday_searchjobs_site_job_detail(self):
        # Workday 站名常叫 "SearchJobs"（如 MSD 默沙东），其岗位**详情**路径形如
        # /SearchJobs/job/{loc}/{title}_{reqid}，含真实 /job/ 段。旧逻辑把 /searchjobs 当子串
        # 一律拦截，会把这些真详情页全误杀（本轮已入源质量验证揪出 MSD 20 岗被误拒）。
        job = RawJob(
            company="MSD 默沙东",
            title="Associate Therapeutic Development Manager",
            jd_url="https://msd.wd5.myworkdayjobs.com/SearchJobs/job/"
                   "HKG---Hong-Kong-Island---Hong-Kong-Lee-Garden-Two/"
                   "Associate-Therapeutic-Development-Manager_R400021",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs"
        )

        self.assertTrue(ok, reason)

    def test_rejects_workday_searchjobs_landing(self):
        # 但 SearchJobs **搜索落地页**（无 /job/ 详情段）仍须拦截，不能因放宽而漏过。
        job = RawJob(
            company="MSD 默沙东",
            title="Search Jobs",
            jd_url="https://msd.wd5.myworkdayjobs.com/SearchJobs",
        )

        ok, reason = normalizer.validate_job_quality(
            job, "https://msd.wd5.myworkdayjobs.com/wday/cxs/msd/SearchJobs/jobs"
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
