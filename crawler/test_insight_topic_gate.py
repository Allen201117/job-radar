"""公开讨论说法层的主题门与数值抽取：只测纯函数，不连网络或数据库。"""
import unittest

import insight_topic_gate as G


class TestTopicClassification(unittest.TestCase):
    def test_off_topic_promotion_samples_are_retired_or_rerouted(self):
        # 这些断言会在关键词缺失、错误的并列处理或放宽转投门槛时失败。
        cases = [
            (
                "据招聘信息，正浩创新为应届生提供有竞争力的薪酬、五险一金、弹性上班、餐饮补贴等专属福利。",
                ("retire", None),
            ),
            (
                "据公开信息，北醒公司电子/电器/通信技术类岗位占比最多，薪酬集中在15-30k范围。",
                ("reroute", "pay_level"),
            ),
            (
                "据公开讨论，三维家的销售岗多数实行单休制度，而其他岗位多为双休。",
                ("reroute", "overtime_level"),
            ),
            (
                "据公开招聘资料，创维集团校招面向2026届海内外毕业生，毕业时间范围为2025年9月至2026年8月。",
                ("retire", None),
            ),
        ]
        for content, expected in cases:
            with self.subTest(content=content):
                self.assertEqual(G.classify_topic(content, "promotion_pace"), expected)

    def test_real_promotion_discussions_are_kept(self):
        cases = [
            "据公开讨论，神策数据重视内部晋升机制，提供均等的职业发展机会。",
            "据公开讨论，华夏银行正式编制岗位享有结构化薪资、多元化福利和清晰的晋升路径。",
        ]
        for content in cases:
            with self.subTest(content=content):
                self.assertEqual(G.classify_topic(content, "promotion_pace"), ("keep", None))

    def test_internship_dominates_ambiguous_conversion_word(self):
        content = "实习生有导师带教，表现优秀可转正，并有实习日薪。"
        self.assertEqual(G.classify_topic(content, "intern_experience"), ("keep", None))
        self.assertNotEqual(G.classify_topic(content, "promotion_pace"), ("reroute", "promotion_pace"))

    def test_empty_or_non_text_content_retires_without_crashing(self):
        for content in ("", None, "！？……"):
            with self.subTest(content=content):
                self.assertEqual(G.classify_topic(content, "promotion_pace"), ("retire", None))


class TestMetricExtraction(unittest.TestCase):
    def test_extracts_bonus_months_and_excludes_non_bonus_months(self):
        self.assertEqual(G.extract_metric_value("bonus_months", "3-6 个月。"), 4.5)
        self.assertEqual(G.extract_metric_value("bonus_months", "年终奖一般发 4 个月。"), 4.0)
        self.assertIsNone(G.extract_metric_value("bonus_months", "试用期 3 个月，入职后缴纳社保。"))

    def test_extracts_interview_rounds_and_excludes_financing_round(self):
        self.assertEqual(G.extract_metric_value("interview_rounds", "流程通常是 3-4 轮面试。"), 3.5)
        self.assertIsNone(G.extract_metric_value("interview_rounds", "公司刚完成第 2 轮融资。"))

    def test_extracts_monthly_pay_in_k_and_rejects_wan(self):
        self.assertEqual(G.extract_metric_value("pay_level", "薪酬范围 15-30k。"), 22.5)
        self.assertEqual(G.extract_metric_value("pay_level", "月薪 15000-30000。"), 22.5)
        self.assertEqual(G.extract_metric_value("pay_level", "base 20k。"), 20.0)
        self.assertIsNone(G.extract_metric_value("pay_level", "年包 20-40万。"))

    def test_non_numeric_topics_do_not_invent_a_value(self):
        self.assertIsNone(G.extract_metric_value("overtime_level", "经常加班到晚上十点。"))


class TestDedupePlan(unittest.TestCase):
    def test_keeps_earliest_duplicate_and_leaves_single_row(self):
        rows = [
            {"id": "later", "company_id": "c1", "content": " 同一条说法 ", "created_at": "2026-09-02T00:00:00Z"},
            {"id": "earlier", "company_id": "c1", "content": "同一条说法", "created_at": "2026-09-01T00:00:00Z"},
            {"id": "only", "company_id": "c2", "content": "单条", "created_at": "2026-09-01T00:00:00Z"},
        ]
        self.assertEqual(G.dedupe_plan(rows), ["later"])


if __name__ == "__main__":
    unittest.main()
