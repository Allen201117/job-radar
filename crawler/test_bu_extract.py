import unittest
from collections import Counter

import bu_extract as B


class CandidateExtractionTest(unittest.TestCase):
    def test_real_title_shapes(self):
        self.assertIn("Glow Studio", B.extract_candidates("游戏场景原画设计实习生-Glow Studio"))
        multi = B.extract_candidates("推荐系统Data For AI开发实习生-Data-抖音/直播/电商/剪映")
        self.assertIn("抖音/直播/电商/剪映", multi)
        self.assertNotIn("Data", multi)
        self.assertIn("主站", B.extract_candidates("UX设计师-【主站】"))
        self.assertIn("腾讯会议", B.extract_candidates("腾讯会议-AI产品经理-ASR方向"))
        self.assertEqual(B.extract_candidates("大模型智能体架构师（J83572）"), [])


class NoiseAndNormalizationTest(unittest.TestCase):
    def test_known_noise_and_real_business_units(self):
        for token in ("27届秋招", "2026校招", "产品实习生", "后端开发实习生", "策略运营实习生", "北京", "中小发西南大区"):
            self.assertTrue(B.is_noise(token), token)
        for token in ("OceanBase", "小米汽车", "飞书", "健康事业群", "TikTok Shop"):
            self.assertFalse(B.is_noise(token), token)
        self.assertTrue(B.is_noise("蚂蚁集团", "蚂蚁集团"))

    def test_bracket_normalization(self):
        self.assertEqual(B.normalize_bu("【主站】"), B.normalize_bu("主站"))

    def test_profile_exact_company_beats_another_profile_alias(self):
        exact, normalized, _ = B.build_profile_index([
            {"id": "a", "company": "甲集团", "aliases": ["乙公司"]},
            {"id": "b", "company": "乙公司", "aliases": []},
        ])
        self.assertEqual(B.resolve_profile("乙公司", exact, normalized)["id"], "b")


class GovernancePlanTest(unittest.TestCase):
    def _company_data(self, count=20):
        return {"c1": {
            "company_id": "c1", "company": "快手", "job_count": 50,
            "candidate_total": count, "counts": Counter({"主站": count}),
            "kept": B.eligible_counts(Counter({"主站": count}), 20),
        }}

    def test_threshold_19_is_not_written_20_is_written(self):
        self.assertEqual(B.eligible_counts(Counter({"主站": 19}), 20), {})
        plan = B.plan_subject_changes(self._company_data(20), [])
        self.assertTrue(any(row["name"] == "主站" for row in plan["insert"]))

    def test_rejected_subject_is_not_revived(self):
        existing = [{"id": "s1", "company_id": "c1", "kind": "business_unit", "name": "主站",
                     "origin": "derived_title", "status": "rejected"}]
        plan = B.plan_subject_changes(self._company_data(), existing)
        self.assertFalse(any(row["name"] == "主站" for row in plan["insert"] + plan["update"]))
        self.assertEqual(plan["rejected_skipped"], 1)

    def test_disappeared_active_subject_is_retired_not_deleted(self):
        existing = [{"id": "s-old", "company_id": "c1", "kind": "business_unit", "name": "旧业务",
                     "origin": "derived_title", "status": "active"}]
        plan = B.plan_subject_changes(self._company_data(), existing)
        self.assertEqual(plan["retire"], [{"id": "s-old", "company_id": "c1", "name": "旧业务"}])
        self.assertNotIn("delete", plan)


class LiveNoiseRegressionTest(unittest.TestCase):
    """2026-09-03 拿 38,491 条真实在招标题跑出来的噪声，逐条钉死。

    修前噪声率 ~14%（超过 spec §5.1 的 <10% 验收线），修后 6.6%。
    这些用例失败 = 有人放松了停用词，业务线表会重新被招聘项目/泛词污染。
    """

    def test_recruiting_programs_and_intern_variants_are_noise(self):
        # 腾讯「新星引力计划」133 次、美团「北斗实习」64 次、蚂蚁「Plan A」40 次
        for token in ("新星引力计划", "北斗实习", "大模型北斗实习", "基座大模型北斗实习",
                      "转正实习", "Plan A", "管培生", "培养生", "可灵AI专项"):
            with self.subTest(token=token):
                self.assertTrue(B.is_noise(token), token)

    def test_generic_terms_are_noise_but_compounds_survive(self):
        # 字节 data(335)、国际化(190)，网易 平台(24) 都是泛词
        for token in ("data", "平台", "国际化", "中台", "方向", "技术", "业务"):
            with self.subTest(token=token):
                self.assertTrue(B.is_noise(token), token)
        # ⚠️ 只做全等判断：含泛词的真业务线不能被误杀
        for token in ("数据平台", "国际电商", "全球技术", "算法引擎部"):
            with self.subTest(token=token):
                self.assertFalse(B.is_noise(token), token)

    def test_countries_and_project_codes_are_noise(self):
        for token in ("malaysia", "Singapore", "日本", "J3", "A1", "UE5"):
            with self.subTest(token=token):
                self.assertTrue(B.is_noise(token), token)

    def test_company_name_itself_is_noise_when_company_passed(self):
        # 蚂蚁集团 641 次：漏传 company 参数就会把公司名当业务线（探针第一版踩过）
        self.assertTrue(B.is_noise("蚂蚁集团", "蚂蚁集团"))
        self.assertFalse(B.is_noise("蚂蚁国际", "蚂蚁集团"))

    def test_real_business_units_survive_all_gates(self):
        # 创始人点名的例子：字节 Seed（实测 229 岗）
        for token, company in (("Seed", "字节跳动"), ("飞书", "字节跳动"),
                               ("火山引擎", "字节跳动"), ("TikTok Shop", "字节跳动"),
                               ("OceanBase", "蚂蚁集团"), ("网商银行", "蚂蚁集团"),
                               ("小象超市", "美团"), ("小米汽车", "小米"),
                               ("主站", "快手"), ("微信视频号", "腾讯"),
                               ("两轮车事业部", "滴滴"), ("第五人格", "网易")):
            with self.subTest(token=token):
                self.assertFalse(B.is_noise(token, company), token)

