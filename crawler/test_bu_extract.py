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



class DisplayNameTest(unittest.TestCase):
    """身份（归一键）与展示名（原始写法）必须分开。

    洞察库页面直接展示 insight_subjects.name；若 name 存 casefold 后的归一键，
    「TikTok Shop」会以「tiktok shop」出现在用户面前。
    """

    def _data(self, titles, company="字节跳动"):
        rows = [{"company": company, "title": t} for t in titles]
        profile = {"id": "c1", "company": company, "aliases": []}
        index = B.build_profile_index([profile])
        data, _ = B.collect_company_data(rows, index, 2)
        return data

    def test_display_keeps_original_casing(self):
        data = self._data(["TikTok Shop-后端工程师", "TikTok Shop-前端工程师"])
        plan = B.plan_subject_changes(data, [])
        names = {row["name"] for row in plan["insert"]}
        self.assertIn("TikTok Shop", names)
        self.assertNotIn("tiktok shop", names)

    def test_most_common_variant_wins(self):
        data = self._data([
            "TikTok Shop-A工程师", "TikTok Shop-B工程师", "tiktok shop-C工程师",
        ])
        plan = B.plan_subject_changes(data, [])
        self.assertIn("TikTok Shop", {row["name"] for row in plan["insert"]})

    def test_existing_row_matched_by_normalized_key_not_display_name(self):
        """已有行写的是旧写法时，应当 update 同一行（并改名），而不是再插一行。"""
        data = self._data(["TikTok Shop-A工程师", "TikTok Shop-B工程师"])
        existing = [{"id": "s1", "company_id": "c1", "kind": "business_unit",
                     "name": "tiktok shop", "origin": "derived_title", "status": "active"}]
        plan = B.plan_subject_changes(data, existing)
        self.assertFalse(any(r["name"].lower() == "tiktok shop" for r in plan["insert"]))
        updated = [r for r in plan["update"] if r["name"] == "TikTok Shop"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["id"], "s1")
        self.assertEqual(plan["retire"], [])

    def test_pick_display_falls_back_when_no_variant_recorded(self):
        self.assertEqual(B.pick_display(Counter(), "飞书"), "飞书")


class EnglishTitleNoiseTest(unittest.TestCase):
    """2026-09-03 第一次跑到外企源上才暴露的噪声，逐条钉死。

    此前 38,491 条验证样本全是中文标题；一接上 Amazon / Apple 这类英文源，
    连字符构词（Multi-Channel / Pre-Sales）就被当成了业务线。
    """

    def test_english_hyphen_is_word_forming_not_a_separator(self):
        for title in ("Multi-Channel Sales Specialist",
                      "Pre-Sales Solutions Architect",
                      "Mixed-Signal Design Engineer"):
            self.assertEqual(B.extract_candidates(title), [], title)

    def test_chinese_titles_still_use_hyphen_convention(self):
        self.assertIn("腾讯云", B.extract_candidates("腾讯云-后端开发工程师"))
        self.assertIn("TikTok Shop", B.extract_candidates("TikTok Shop-电商产品经理"))

    def test_bracket_form_survives_in_english_titles(self):
        # 【X】是显式标注，不是构词，英文标题里同样可信
        self.assertIn("Seed", B.extract_candidates("【Seed】Research Scientist"))

    def test_english_role_nouns_are_noise(self):
        for token in ("manager", "Genius", "Engineer", "analysts", "director"):
            self.assertTrue(B.is_noise(token), token)

    def test_region_abbreviations_are_noise(self):
        for token in ("us", "EMEA", "apac", "latam"):
            self.assertTrue(B.is_noise(token), token)


class SecondRoundLiveNoiseTest(unittest.TestCase):
    """2026-09-03 全库跑完后抽检 100 条业务线，逐类钉死。

    修前噪声率 ~13%（超过 spec §5.1 的 <10% 验收线），来源是四类：
    半个括号的碎片 / 招聘类型全称 / 区域名 / 一线岗位名。
    """

    def test_unbalanced_bracket_fragment_is_repaired_not_displayed(self):
        # live：「基石产品线）」「综合创新线）」「肿瘤创新线）」带着半个括号进了库
        self.assertEqual(B._strip_unbalanced("基石产品线）"), "基石产品线")
        self.assertEqual(B._strip_unbalanced("（综合创新线"), "综合创新线")
        # 配对的括号不动
        self.assertEqual(B._strip_unbalanced("剪映CapCut（国际）"), "剪映CapCut（国际）")

    def test_recruitment_type_full_names_are_noise(self):
        for token in ("社会招聘", "内部招聘", "校园招聘", "培训生", "储备生",
                      "CRC Intern", "Graduate Program", "Trainee"):
            self.assertTrue(B.is_noise(token), token)

    def test_region_names_are_noise_but_real_subsidiaries_survive(self):
        for token in ("中国", "华东", "亚太", "大中华区"):
            self.assertTrue(B.is_noise(token), token)
        # 只做全等判断 → 真子公司不受影响
        for token in ("外运华东", "长城国际", "蚂蚁国际"):
            self.assertFalse(B.is_noise(token), token)

    def test_frontline_job_titles_are_noise(self):
        for token in ("店员", "维修技师", "区域业代", "高级研究员", "财务岗"):
            self.assertTrue(B.is_noise(token), token)

    def test_real_business_units_from_the_same_sample_survive(self):
        for token in ("淘宝闪购", "剪映CapCut", "达摩院", "网商银行", "微信小店",
                      "无人车业务部", "国际事业群IBG", "番茄小说", "豆包", "阿里妈妈"):
            self.assertFalse(B.is_noise(token), token)


class ProfileProvisionTest(unittest.TestCase):
    """没有画像的公司整家进不了洞察库——这是覆盖率只有一半的真因。"""

    def test_only_companies_above_threshold_get_a_profile(self):
        rows = B.plan_new_profiles({"A公司", "B公司"}, 10, {"A公司": 45, "B公司": 3})
        self.assertEqual([r["company"] for r in rows], ["A公司"])

    def test_new_profiles_do_not_jump_the_enrichment_queue(self):
        # 富化队列按 insight_checked_at nulls first 取活；留空会让长尾插队抢 LLM/搜索预算
        rows = B.plan_new_profiles({"A公司"}, 1, {"A公司": 5})
        self.assertTrue(rows[0]["insight_checked_at"])
