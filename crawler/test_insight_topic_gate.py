"""公开讨论说法层的主题门与数值抽取：只测纯函数，不连网络或数据库。"""
import unittest

import insight_topic_gate as G
import insight_topic_gate as gate


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


class WriteSideGateTest(unittest.TestCase):
    """写入端主题门：存量清一次只解决历史，不装写入门等于今天白清。"""

    def test_real_off_topic_samples_are_blocked_before_writing(self):
        # 这四条是 2026-09-03 线上实测挂在「晋升发展」下的真实内容
        cases = [
            ("据招聘信息，正浩创新为应届生提供有竞争力的薪酬、五险一金、弹性上班、餐饮补贴等专属福利。", "retire"),
            ("据公开招聘资料，创维集团校招面向2026届海内外毕业生，毕业时间范围为2025年9月至2026年8月。", "retire"),
        ]
        for content, expected in cases:
            action, key, dim = gate.gate_new_claim(content, "晋升发展")
            self.assertEqual(action, expected, content[:20])
            self.assertIsNone(key)

    def test_misfiled_but_useful_content_is_rerouted_with_its_dimension(self):
        action, key, dim = gate.gate_new_claim(
            "据公开讨论，三维家的销售岗多数实行单休制度，而其他岗位多为双休。", "晋升发展")
        self.assertEqual((action, key, dim), ("reroute", "overtime_level", "culture"))
        action, key, dim = gate.gate_new_claim(
            "据公开信息，北醒公司电子/网络技术类岗位占比最多，薪酬集中在15-30k范围。", "晋升发展")
        self.assertEqual((action, key, dim), ("reroute", "pay_level", "compensation_intensity"))

    def test_on_topic_content_is_kept(self):
        action, key, dim = gate.gate_new_claim(
            "据公开讨论，神策数据重视内部晋升机制，提供均等的职业发展机会", "晋升发展")
        self.assertEqual((action, key, dim), ("keep", "promotion_pace", "path"))

    def test_unregistered_topic_passes_through_without_a_metric_key(self):
        # 「公开讨论」这类兜底包不参与主题门，不能因为没登记就被误杀
        self.assertEqual(gate.gate_new_claim("任意内容", "公开讨论"), ("keep", None, None))

    def test_topic_map_matches_the_query_catalog(self):
        """T3 查询包里的每个主题都必须能映射到 metric_key，否则新条目又变成不可筛的散文。"""
        import insight_backlog
        for name in insight_backlog.T3_TOPIC_CATALOG:
            self.assertIn(name, gate.TOPIC_TO_METRIC, f"主题「{name}」没有 metric_key 映射")

    def test_every_metric_has_a_dimension(self):
        for key in set(gate.TOPIC_TO_METRIC.values()) | {"pay_level"}:
            self.assertIn(key, gate.METRIC_TO_DIMENSION, key)


class ClaimTypeGateTest(unittest.TestCase):
    """说法类型门：metric_key 必须与「这句在断言什么」一致，不能只跟着「在讲谁」走。

    2026-09-17 live：3 个档位主题共 195 条判不出档，intern_experience 占 152 条，
    其中 54 条讲薪资、32 条讲门槛、27 条讲福利，真讲实习体验强弱的只有 23 条。
    下面每条 content 都是当时库里的原文。
    """

    def test_intern_pay_and_perks_do_not_enter_the_grade_queue(self):
        # 分档队列只按 metric_key 取数（insight_grade_extract._load_rows），
        # 所以「不进队列」的唯一正确表达就是 metric_key 为 None。
        cases = [
            ("据公开讨论，中国能建实习生转正后的薪资范围在5000-12000元/月。", "compensation_intensity"),
            ("据招聘信息显示，哈啰为实习生提供健身房和食堂等福利", "compensation_intensity"),
            ("财务实习生岗位学历要求严格，郑州地区招聘均要求本科及以上学历", "hiring"),
            ("据招聘信息显示，AMD硬件平台验证设计实习生需具备Python/Ruby脚本开发调试经验。", "hiring"),
        ]
        for content, dimension in cases:
            action, key, dim = gate.gate_new_claim(content, "实习体验")
            self.assertIsNone(key, content[:24])
            self.assertEqual(dim, dimension, content[:24])
            self.assertEqual(action, "reroute", content[:24])

    def test_real_intern_experience_keeps_its_scale(self):
        for content in [
            "据报道，公司对新员工有导师带教制度，帮助快速融入和成长。",
            "据公开讨论，Squarespace的实习生转正后有明确的晋升路径，从员工到技工再到主管和副总。",
            "据公开讨论，有实习生反映公司氛围适合喜欢科研、专注创新和解决问题的同学。",
        ]:
            action, key, dim = gate.gate_new_claim(content, "实习体验")
            self.assertEqual((action, key, dim), ("keep", "intern_experience", "culture"), content[:24])

    def test_intern_pay_is_not_routed_into_pay_level(self):
        """实习日薪 / 津贴与 pay_level 的全职月薪 K 不是一个量纲，混进去会把中位数拉垮。"""
        _action, key, dim = gate.gate_new_claim(
            "据招聘信息显示，米哈游实习生薪资按日计算，日薪范围在150-300元之间。", "实习体验")
        self.assertIsNone(key)
        self.assertEqual(dim, "compensation_intensity")

    def test_non_intern_pay_still_routes_to_pay_level(self):
        # 主语不是实习时，纯薪资说法照旧进 pay_level（有全职月薪量纲，可比）。
        _action, key, dim = gate.gate_new_claim(
            "据员工爆料，小米涨薪幅度通常为8%-10%，薪资较低的员工可能获得20%的涨幅。", "晋升发展")
        self.assertEqual((key, dim), ("pay_level", "compensation_intensity"))

    def test_mixed_promotion_and_pay_stays_on_promotion(self):
        """「Senior 职级薪资可达 1 万新元」两边各命中一词 → 让位闸保原判，不瞎改。"""
        _action, key, _dim = gate.gate_new_claim(
            "据公开讨论，Grab的Senior职级薪资可达1万新元以上。", "晋升发展")
        self.assertEqual(key, "promotion_pace")

    def test_original_scale_wins_when_it_has_any_signal_of_its_own(self):
        """让位闸：原量表命中一个词就留着。收紧成「得分最高才留」实测把全库反向误伤从 119 抬到 168。"""
        action, key, _dim = gate.gate_new_claim(
            "据报道，公司提供弹性工作制，包括双休、节日福利和定期团建活动。", "加班文化")
        self.assertEqual((action, key), ("keep", "overtime_level"))
        action, key, _dim = gate.gate_new_claim(
            "据行业观察，美国初创企业主动要求员工遵循996的数量在过去一年至少翻了一番。", "加班文化")
        self.assertEqual((action, key), ("keep", "overtime_level"))

    def test_a_real_extracted_number_always_wins(self):
        """数值抽取器抽出了值 = 比任何词表都硬的证据，不许被福利词摘掉 key。"""
        content = "据公开讨论，某公司年终奖普遍发放3-6个月，另有五险一金等福利。"
        self.assertIsNotNone(gate.extract_metric_value("bonus_months", content))
        _action, key, _dim = gate.gate_new_claim(content, "年终奖")
        self.assertEqual(key, "bonus_months")

    def test_ambiguous_content_keeps_the_original_key(self):
        """并列最高 / 零命中一律弃权：宁可少改一条，也不要把好条目改坏。"""
        self.assertIsNone(gate.classify_claim_type("据公开讨论，这家公司挺不错的。"))
        self.assertEqual(gate.route_by_claim_type("据公开讨论，这家公司挺不错的。", "overtime_level"),
                         ("overtime_level", "culture"))

    def test_every_claim_type_has_a_dimension(self):
        for claim_type in gate.CLAIM_TYPE_KEYWORDS:
            self.assertIn(claim_type, gate.CLAIM_TYPE_TO_DIMENSION, claim_type)
        for claim_type, metric in gate.CLAIM_TYPE_TO_METRIC.items():
            if metric:
                self.assertIn(metric, gate.METRIC_TO_DIMENSION, metric)

    def test_bare_transfer_word_is_not_a_mentoring_signal(self):
        """「实习生转正后的薪资……」几乎人人都写，收裸「转正」这道门就白装了。"""
        self.assertNotIn("转正", gate.CLAIM_TYPE_KEYWORDS["mentoring"])
