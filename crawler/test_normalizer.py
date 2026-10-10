import json
import os
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
        # 月日补零成 ISO：前端只认 YYYY-MM-DD，不补零的真截止日一直显示不出来。
        self.assertEqual(normalizer.extract_deadline("投递截止：2026年6月30日"), "2026-06-30")
        self.assertEqual(normalizer.extract_deadline("长期有效，欢迎随时投递"), "长期有效")
        self.assertEqual(
            normalizer.extract_deadline("Applications are reviewed on a rolling basis."), "长期有效")
        # 同一句里没有招聘类词的 rolling basis 说的可能是奖金、项目、入职时间。
        self.assertIsNone(normalizer.extract_deadline("rolling basis"))
        self.assertIsNone(normalizer.extract_deadline("岗位职责：写代码"))

    def test_deadline_shared_cases(self):
        """与前端 lib/job-fields.extractDeadline 共读同一份用例（JS 侧断言在 tests/job-fields.test.js）。

        2026-10-10 香港库全集：全库 30,507 行「长期有效」里，库里正文真写着「长期有效 / 长期招聘」的
        只有 43 行，其余几乎都是英文 JD 福利条款里的 long-term / rolling 触发的；「截至 + 日期」多是
        年龄、工龄的计算基准日或公司介绍里的统计时点，不是投递截止日。
        同日复核：正文含这两个中文词的在招岗 55 行里，是招聘声明的只有 3 行（其余是「建立长期有效合作关系」
        一类）——所以中文也要看前后文；带 src 的用例是这次逐条看过的库内正文与官网全文。
        """
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "tests", "fixtures", "deadline-text-cases.json")
        with open(path, encoding="utf-8") as f:
            cases = json.load(f)["cases"]
        self.assertGreaterEqual(len(cases), 25)
        for case in cases:
            self.assertEqual(normalizer.extract_deadline(case["text"]), case["expect"], case["text"])

    def test_deadline_look_back_stops_at_sentence_boundary(self):
        """资格条件词只在**同一句**里才算数：上一句讲年龄计算，不该连累下一句的报名截止。"""
        self.assertEqual(
            normalizer.extract_deadline("年龄计算至今。报名截止2026年9月25日"), "2026-09-25")

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


class StripNulTest(unittest.TestCase):
    """回归守卫：抓到的文本里混进 NUL(0x00) 不能把整源写库炸掉。

    2026-07-28 线上：laiyifen.zhiye.com（来伊份）的岗位文本含 NUL，psycopg2 抛
    `ValueError: A string literal cannot contain NUL (0x00) characters`，
    **整源那一轮全部写不进去**（不是丢一条），每天固定挂 2 次连挂多日。
    清洗器原有的 re.sub(r"\s+", " ") 治不了——\x00 不属于 \s，会穿透到写库那刻才炸。
    """

    def test_strip_nul_only_removes_nul(self):
        self.assertEqual(normalizer.strip_nul("a\x00b"), "ab")
        self.assertEqual(normalizer.strip_nul("干净文本"), "干净文本")
        # 其它控制字符 Postgres 存得下，不该被动（动了就改了正文）
        self.assertEqual(normalizer.strip_nul("a\tb\nc"), "a\tb\nc")
        self.assertIsNone(normalizer.strip_nul(None))
        self.assertEqual(normalizer.strip_nul(123), 123)

    def test_cleaners_drop_nul(self):
        self.assertNotIn("\x00", normalizer.clean_title("后端\x00工程师"))
        self.assertNotIn("\x00", normalizer.clean_summary("负责\x00后端研发") or "")
        self.assertNotIn("\x00", normalizer.clean_salary("20\x00k") or "")
        loc = normalizer.clean_location("上海\x00")
        self.assertNotIn("\x00", loc or "")

    def test_normalize_output_has_no_nul_in_any_field(self):
        raw = RawJob(
            company="来伊份\x00",
            title="门店运营\x00专员",
            location="上海\x00",
            summary="负责\x00门店运营",
            jd_url="https://laiyifen.zhiye.com/social/detail?jobAdId=abc\x00",
            apply_url="https://laiyifen.zhiye.com/social/detail?jobAdId=abc\x00",
            salary_text="8\x00k",
            experience="3\x00年",
            education="本科\x00",
            deadline="2026-12-31\x00",
        )
        row = normalizer.normalize(raw, source_id="s1", company="来伊份")
        offenders = [k for k, v in row.items() if isinstance(v, str) and "\x00" in v]
        self.assertEqual(offenders, [], f"这些字段仍带 NUL，会把整源写库炸掉: {offenders}")
        self.assertEqual(row["company"], "来伊份")
        self.assertEqual(row["title"], "门店运营专员")


class TaiwanRejectionTests(unittest.TestCase):
    """台湾岗必须在 validate_job_quality 这一步就被拦下，不许写进 jobs 表。

    2026-09-18 实测：香港库 48 行 active + country_code='TW' 全部来自两类根因——
    ① workday 的 trusted 分支整批跳过 per-job 复核（HP/3M/NXP/NVIDIA/Abbott/Cisco/
       Medtronic/Alcon/HPE/Sanofi/JLL）；② 纯本土 CN adapter（feishu/hotjob/wt/
       beisen/xiaomi_feishu）压根不调用 location_in_source_regions（小米/TCL/用友网络/
       科大讯飞/安克创新/芯海科技/欢乐互娱）。两类都绕不开 validate_job_quality——
       它是 run.py 对每个 raw job 唯一的、adapter 无关的必经关卡。
    """

    def _job(self, location, jd_url="https://example.com/job/123"):
        return RawJob(company="测试公司", title="工程师", location=location, jd_url=jd_url)

    def test_rejects_real_leaked_locations(self):
        # 全部取自 2026-09-18 香港库 active 岗的真实 location 写法（改前会被判 job_scope=overseas
        # 并放行入库；改后必须在 validate_job_quality 这一步就被拦下）。
        for location in (
            "Taipei, Taipei, City, Taiwan, Region",
            "台北市",
            "TW, Taipei, City, Taipei",
            "Hsinchu",
            "Taiwan, Hsinchu",
            "Taiwan, Taipei",
            "台湾省",
            "Taiwan, , , Taipei",
            "Taiwan, , Taichung, , CVL, Group, Headquarters, Bldg",
            "Taipei, Taiwan",
            "Taichung, Taichung, Taiwan",
            "Taipei, Taipei, Taiwan",
            "Taipei, Taiwan, China",
        ):
            with self.subTest(location=location):
                ok, reason = normalizer.validate_job_quality(self._job(location), "https://example.com/jobs")
                self.assertFalse(ok, f"{location} 应被拒收")
                self.assertIn("taiwan", reason)

    def test_multi_location_with_taiwan_is_rejected_too(self):
        # 「泰国,越南,台北市」这类一岗多地写法：derive_country_code 与 is_rejected_location
        # 共享同一套优先级（TW 排在 _COUNTRY_TOKENS 靠前、"台北"是子串匹配），会先判成 TW
        # 整条拒收，即使该岗可能主要在泰国/越南——这是跟随既有 derive_country_code 顺序的
        # 既定取舍，不是本次改动新引入的规则（见 crawler/geo.py is_rejected_location 注释）。
        ok, reason = normalizer.validate_job_quality(self._job("泰国,越南,台北市"), "https://example.com/jobs")
        self.assertFalse(ok)
        self.assertIn("taiwan", reason)

    def test_does_not_reject_non_taiwan_locations(self):
        # 双向核验的另一半：非台湾地点一个都不许被这条新规则误杀。
        for location in (
            "北京", "上海市", "深圳", "香港", "澳门", "New York, NY", "Singapore",
            "Tokyo, Japan", "Seoul, South Korea", "邢台南和区", "常州新北区", "福州连江县",
            "北海市", "Beijing, China", "青岛市、日本、潍坊市", "远程",
        ):
            with self.subTest(location=location):
                ok, reason = normalizer.validate_job_quality(self._job(location), "https://example.com/jobs")
                self.assertTrue(ok, f"{location} 被误杀: {reason}")


class CleanTitleTailTest(unittest.TestCase):
    """标题里「 - 」后面那一段：只有和这个岗自己的地点字段重复才截，其余一律保留。

    用例全部取自 2026-10-10 live 抓到的 adapter 出口原始标题。那一轮量的是 966 个源、281,084 个岗
    （库里存的是截断后的标题，量不出来，只能从 adapter 出口量；Moka / 国聘 / 比亚迪等要开浏览器或逐岗核验的源没量）：
      · 旧规则（见到「 - 」就把后面全截掉）动了 27,833 个标题（9.90%）。截掉的那一段按「是不是与该岗地点字段对得上 /
        是不是地名词」独立打标：岗位名 · 方向 · 团队 25,386（91.2%），地点 2,043（7.3%），实习 · 编号这类 404（1.5%）。
      · 不同的岗被洗成同一个名字：旧规则 15,327 个岗，新规则 718 个（剩下的是同岗多地、只差末尾城市）。
      · 新旧对拍，两个方向：不该截的保住 25,785；与地点字段重复的照旧截掉 759；像地点但没截的 1,284
        （845 是销售大区 / Remote / Hybrid 这类地点字段里没有的信息，439 是同一个地方写法不同——主要是州缩写对全称）；
        旧规则不动、新规则却动了的 0。
    拿这批原始标题重量的方法：逐源跑 adapter.fetch + parse（CRAWL_DETAIL_CAP=0），对每个 RawJob 比
    旧正则、clean_title(title, raw.location, clean_location(raw.location)) 与原文三者。
    """

    def test_role_after_separator_survives(self):
        # 财通证券：改前三行入库后都叫「杭州金城路证券营业部」。
        titles = [
            "杭州金城路证券营业部 - 副总经理",
            "杭州金城路证券营业部 - 财富顾问",
            "杭州金城路证券营业部 - 业务副总经理",
        ]
        cleaned = [normalizer.clean_title(t, "杭州市", "杭州") for t in titles]
        self.assertEqual(cleaned, titles)
        self.assertEqual(len(set(cleaned)), 3)

    def test_team_direction_and_meta_tails_are_kept(self):
        for title, location in (
            ("Software Engineer - Computer Vision", "San Mateo, CA United States"),
            ("算法架构工程师 - 训练框架方向", "北京"),
            ("AI产品设计师 - 飞书设计", "北京"),
            ("Agent研发工程师 - 抖音用户增长", "北京"),
            ("Machine Learning Researcher - Intern", "New York"),
            ("Tech Ops Engineer II - AMZ10364799", "Florence, Kentucky, United States"),
            ("Retail - Lead Store Advisor（WUHAN SKP）", "Wuhan"),
        ):
            with self.subTest(title=title):
                self.assertEqual(normalizer.clean_title(title, location, normalizer.clean_location(location)), title)

    def test_tail_repeating_the_location_field_is_dropped(self):
        for title, location, expected in (
            ("Customer Success Manager - Boston", "Boston, Massachusetts, USA", "Customer Success Manager"),
            ("Sales Engineer - UK", "Remote - UK", "Sales Engineer"),
            ("Field Calibration Technician - Remote", "Remote United States", "Field Calibration Technician"),
            ("Sr. Manager, Medical Education-AMI Programs - Irvine, CA", "Irvine, CA, United States",
             "Sr. Manager, Medical Education-AMI Programs"),
            ("软件工程师 - 上海", "上海市-浦东新区", "软件工程师"),
            ("软件工程师 - 上海市", "上海", "软件工程师"),
            ("销售经理 — 北京/上海", "北京、上海", "销售经理"),
            # 标题写英文、地点字段给中文：靠 CITY_ALIASES 对上。
            ("Site Reliability Engineer - Singapore", "新加坡", "Site Reliability Engineer"),
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    normalizer.clean_title(title, location, normalizer.clean_location(location)), expected)

    def test_only_trailing_location_segments_go(self):
        for title, location, expected in (
            ("Staff Frontend Engineer - UI Platform - Seattle", "Seattle, Washington",
             "Staff Frontend Engineer - UI Platform"),
            ("招聘专员（外包） - 产研 - 北京", "北京", "招聘专员（外包） - 产研"),
            ("Engineer - Shanghai - China", "Shanghai, China", "Engineer"),
            # 地点在中间：后面还有内容，不动。
            ("Engineer - Shanghai - Payments", "Shanghai", "Engineer - Shanghai - Payments"),
            # 第一段永远留着，哪怕它自己就是个地名。
            ("上海 - 软件工程师", "上海", "上海 - 软件工程师"),
            ("Shanghai - Beijing", "Shanghai, Beijing", "Shanghai"),
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    normalizer.clean_title(title, location, normalizer.clean_location(location)), expected)

    def test_place_like_tail_not_in_location_field_is_kept(self):
        # 销售大区 / 驻地 / 办公方式：地点字段里没有这条信息，截掉就丢了。
        for title, location in (
            ("Territory Account Executive - West", "United States"),
            ("Clinical Account Executive, Multiple Myeloma - Austin, TX", "Remote United States"),
            ("Sr. Client Account Manager (Growth) - Greater China Region", "Singapore, SG"),
            ("Software Engineer - Shanghai (Hybrid)", "Shanghai"),
            ("激光雷达算法专家 - 上海/北京", "上海"),
            # 州缩写不换算：地点写的是全称，尾巴留着（只是好不好看的问题）。
            ("Area Manager - Tracy, CA", "Tracy, California, United States"),
            # 西文按整词比，不做子串。
            ("Designer - Art", "Stuttgart, Germany"),
            # 方位词是销售大区，哪怕地点字段里恰好有这个词。
            ("Territory Account Executive - South", "South San Francisco, CA"),
            ("Enterprise Account Executive - East", "East Hanover, NJ"),
            # 括号里的「 - 」不是分段：从那里截会留下半个括号。
            ("Software Engineer (Remote - US)", "Remote, US"),
            ("Point72 Academy Investment Analyst Program (2027 – HK)", "HK"),
        ):
            with self.subTest(title=title):
                self.assertEqual(normalizer.clean_title(title, location, normalizer.clean_location(location)), title)

    def test_without_location_nothing_is_dropped(self):
        self.assertEqual(normalizer.clean_title("有机合成研究员 - 西安"), "有机合成研究员 - 西安")
        self.assertEqual(normalizer.clean_title("Engineer - Shanghai", None, None), "Engineer - Shanghai")
        self.assertEqual(normalizer.clean_title("Engineer - Shanghai", "", None), "Engineer - Shanghai")

    def test_whitespace_and_compact_hyphens(self):
        self.assertEqual(normalizer.clean_title("  部门-角色-方向  ", "北京"), "部门-角色-方向")
        self.assertEqual(normalizer.clean_title("营业部   -   副总经理", "杭州"), "营业部 - 副总经理")
        self.assertEqual(normalizer.clean_title("软件工程师-上海", "上海"), "软件工程师-上海")

    def _normalize(self, title, location):
        raw = RawJob(company="测试公司", title=title, location=location,
                     jd_url="https://example.com/job/123")
        return normalizer.normalize(raw, source_id="s1", company="测试公司")

    def test_normalize_keeps_distinct_roles_distinct(self):
        a = self._normalize("杭州金城路证券营业部 - 副总经理", "杭州市")
        b = self._normalize("杭州金城路证券营业部 - 财富顾问", "杭州市")
        self.assertEqual(a["title"], "杭州金城路证券营业部 - 副总经理")
        self.assertNotEqual(a["title"], b["title"])
        self.assertNotEqual(a["content_hash"], b["content_hash"])

    def test_normalize_sees_intern_written_after_the_separator(self):
        # 招聘类型的实习判定只认标题：尾巴被截掉时这类岗会被当成社招。
        job = self._normalize("Machine Learning Researcher - Intern", "New York")
        self.assertEqual(job["job_type"], "实习")

    def test_normalize_title_city_fallback_reads_kept_tail(self):
        # 地点字段为空时尾巴留在标题里，标题城市兜底才认得出来。
        job = self._normalize("有机合成研究员 - 西安", None)
        self.assertEqual(job["title"], "有机合成研究员 - 西安")
        self.assertEqual(job["location"], "西安")
