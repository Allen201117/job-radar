"""中英双语关键词扩展/匹配的纯函数单测（移植自 lib/china-keyword-expansion.test.js 的关注点）。"""
import unittest

import china_keyword_expansion as cke


class NormalizeTest(unittest.TestCase):
    def test_lowercase_and_collapse_whitespace(self):
        self.assertEqual(cke.normalize_for_match("  Machine   Learning  "), "machine learning")
        self.assertEqual(cke.normalize_for_match(None), "")


class ContainsTermBoundaryTest(unittest.TestCase):
    def test_short_latin_uses_word_boundary(self):
        self.assertTrue(cke.contains_term("ai engineer", "ai"))
        self.assertTrue(cke.contains_term("senior ml researcher", "ml"))
        # 误匹配防护：maintain/google 不应被 ai/go 命中
        self.assertFalse(cke.contains_term("maintenance technician", "ai"))
        self.assertFalse(cke.contains_term("google maps lead", "go"))

    def test_long_or_cjk_uses_substring(self):
        self.assertTrue(cke.contains_term("machine learning engineer", "machine learning"))
        self.assertTrue(cke.contains_term("后端工程师", "后端"))
        self.assertFalse(cke.contains_term("财务分析", "算法"))


class ExpandTest(unittest.TestCase):
    def test_chinese_expands_to_english_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("算法"))
        for t in ("算法", "machine learning", "ml", "algorithm"):
            self.assertIn(t, terms, t)

    def test_english_expands_to_chinese_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("backend"))
        for t in ("backend", "后端", "服务端"):
            self.assertIn(t, terms, t)

    def test_empty_query_returns_empty(self):
        self.assertEqual(cke.expand_china_keyword_terms(""), [])
        self.assertEqual(cke.expand_china_keyword_terms("   "), [])

    def test_unmatched_term_kept_verbatim(self):
        # 不在任何同义词组里的词应原样保留，仍可做子串匹配
        self.assertIn("blockchain", cke.expand_china_keyword_terms("blockchain"))


class QueryMatchesTest(unittest.TestCase):
    def test_chinese_query_matches_english_job(self):  # 核心 #4 场景
        self.assertTrue(cke.query_matches("Machine Learning Engineer", "算法"))
        self.assertTrue(cke.query_matches("AI Researcher", "算法"))
        self.assertTrue(cke.query_matches("Product Manager", "产品"))

    def test_english_query_matches_chinese_job(self):
        self.assertTrue(cke.query_matches("后端工程师 字节跳动", "backend"))

    def test_no_false_positive_via_short_abbrev(self):
        # 「算法」扩展含 "ai"，但 maintain/maintenance 不应被命中
        self.assertFalse(cke.query_matches("Maintenance Technician — maintain systems", "算法"))

    def test_empty_query_matches_all(self):
        self.assertTrue(cke.query_matches("anything", ""))

    def test_unrelated_query_no_match(self):
        self.assertFalse(cke.query_matches("Finance Analyst report", "前端"))


class ParityWithFrontendTest(unittest.TestCase):
    def test_group_count_matches_frontend(self):
        # 与 lib/china-keyword-expansion.js 的 21 组保持一致
        self.assertEqual(len(cke.CHINA_KEYWORD_GROUPS), 21)

    def test_group_functions_aligned(self):
        self.assertEqual(len(cke.KEYWORD_GROUP_FUNCTIONS), len(cke.CHINA_KEYWORD_GROUPS))


class ClassifyJobFunctionTest(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(cke.classify_job_function("AI 产品经理"), "产品")
        self.assertEqual(cke.classify_job_function("推荐算法工程师"), "研发")
        self.assertEqual(cke.classify_job_function("视觉设计师"), "设计")
        self.assertEqual(cke.classify_job_function("数据分析师"), "数据")
        self.assertEqual(cke.classify_job_function(""), "其他")

    def test_product_precedes_algorithm(self):
        self.assertEqual(cke.classify_job_function("AI 产品经理", "", "了解算法"), "产品")

    def test_title_first_not_misled_by_job_type(self):
        # 标题优先：job_type/summary 不带偏标题已明确的职能（与 JS 同口径）。
        # 实锤：B站「数据科学家」挂部门 job_type=「产品运营类」下，仍应判数据。
        self.assertEqual(
            cke.classify_job_function("商业化-数据科学家（AI Agent 开发方向）", "产品运营类"), "数据"
        )
        self.assertEqual(
            cke.classify_job_function("算法工程师", "产品技术", "与产品经理协作"), "研发"
        )
        # 「职能」例外：招聘活动标签标题退回看正文真实角色。
        self.assertEqual(
            cke.classify_job_function("2024 届校园招聘", "", "产品经理方向，负责需求管理"), "产品"
        )
        self.assertEqual(cke.classify_job_function("招聘专员", "", "负责候选人寻访"), "职能")

    def test_non_software_engineering_not_rd(self):
        # 机械/工艺/化工等非软件工程岗仅靠泛词落入研发 → 归「其他」，不被「算法/AI/数据」类查询误召。
        self.assertEqual(cke.classify_job_function("工艺技术开发（机械/自动化）"), "其他")
        self.assertEqual(cke.classify_job_function("机械工程师"), "其他")
        self.assertEqual(cke.classify_job_function("化工工艺开发"), "其他")
        # 带软件信号的交叉岗仍判研发（保守降级，不误伤机器人/嵌入式）。
        self.assertEqual(cke.classify_job_function("机械臂算法工程师"), "研发")
        self.assertEqual(cke.classify_job_function("汽车嵌入式软件工程师"), "研发")


class JobMatchesTest(unittest.TestCase):
    """字段感知 + 职能门：发现端（刷新公司库 / 联网发现）精准过滤的核心，与前端看板同口径。"""

    def test_cross_function_precision_pm_not_algo(self):  # 用户原始痛点
        algo = ("推荐算法工程师", "负责推荐产品的算法模型，机器学习")
        data = ("数据分析师", "SQL 业务分析，支撑产品决策")
        self.assertFalse(cke.job_matches(algo[0], algo[1], "pm"), "正文含'产品'的算法岗不应命中 pm")
        self.assertFalse(cke.job_matches(data[0], data[1], "pm"), "正文含'产品'的数据岗不应命中 pm")

    def test_cross_function_precision_reverse(self):
        pm = ("产品经理", "了解算法优先，负责需求管理")
        self.assertFalse(cke.job_matches(pm[0], pm[1], "算法"), "PM 岗正文提'算法'不应命中'算法'")

    def test_body_recall_same_function(self):
        # 标题没体现、正文具体词点明角色 + 同职能 → 仍命中（保留召回）
        self.assertTrue(cke.job_matches("2024 届校园招聘", "产品经理方向，负责需求管理", "pm"))
        self.assertTrue(cke.job_matches("资深工程师", "负责推荐算法与模型训练", "算法"))

    def test_real_jobs_match_via_title(self):
        self.assertTrue(cke.job_matches("策略产品经理", "", "pm"))
        self.assertTrue(cke.job_matches("Senior Product Manager", "", "pm"))

    def test_scattered_company_token_matches_body(self):
        self.assertTrue(cke.job_matches("前端工程师", "字节跳动", "前端 字节"))
        self.assertFalse(cke.job_matches("前端工程师", "字节跳动", "前端 腾讯"))

    def test_empty_query_matches_all(self):
        self.assertTrue(cke.job_matches("任意岗位", "任意正文", ""))


if __name__ == "__main__":
    unittest.main()
