import contextlib
import io
import os
import sys
import unittest
from collections import Counter
from unittest import mock

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


def _subject(sid, company_id, *, kind="company", name="某公司", job_count=10,
             status="active", origin="derived_title"):
    return {"id": sid, "company_id": company_id, "kind": kind, "name": name,
            "origin": origin, "job_count": job_count, "status": status}


class ZeroJobCompanyPlanTest(unittest.TestCase):
    """有 active 主体、但这一轮一个在招岗都没归到的公司，也要对账。

    旧实现只遍历「有在招岗」的公司：一家公司的岗全部下架 / 被改名之后，它再也不出现在
    company_data 里，公司主体的 job_count 就永远停在最后一次有岗时的值——洞察库卡面
    写「在招 236 个岗位」，实际 0 个（2026-10-10 真库 100 家、卡面旧数合计约 9 千）。
    """

    def test_company_subject_goes_to_zero_and_title_derived_units_retire(self):
        existing = [
            _subject("s-co", "c1", name="和睦家医疗", job_count=236),
            _subject("s-bu", "c1", kind="business_unit", name="养老", job_count=92),
        ]
        plan = B.plan_zero_job_changes(existing, matched_company_ids=set(),
                                       known_company_ids={"c1"})
        self.assertEqual(plan["zero"], [{"id": "s-co", "company_id": "c1",
                                         "name": "和睦家医疗", "job_count": 236}])
        self.assertEqual(plan["retire"], [{"id": "s-bu", "company_id": "c1", "name": "养老",
                                           "job_count": 92}])
        # 公司主体只归零、不退役：公司级的官方事实 / 公开说法都挂在它上面，退役它等于整家从洞察库消失。
        self.assertEqual(plan["company_ids"], ["c1"])

    def test_company_that_matched_jobs_this_round_is_untouched(self):
        existing = [_subject("s-co", "c1", job_count=50),
                    _subject("s-bu", "c1", kind="business_unit", name="主站", job_count=30)]
        plan = B.plan_zero_job_changes(existing, matched_company_ids={"c1"},
                                       known_company_ids={"c1"})
        self.assertEqual((plan["zero"], plan["retire"], plan["company_ids"]), ([], [], []))

    def test_company_whose_profile_was_not_loaded_is_untouched(self):
        # 画像没读到 = 这家公司这一轮根本没法归属岗位，「没归到」不等于「0 岗」。
        existing = [_subject("s-co", "c-ghost", job_count=50)]
        plan = B.plan_zero_job_changes(existing, matched_company_ids=set(),
                                       known_company_ids=set())
        self.assertEqual((plan["zero"], plan["retire"]), ([], []))

    def test_governance_states_and_other_origins_are_left_alone(self):
        existing = [
            _subject("s-co", "c1", job_count=0),   # 已经是 0：不重复写
            _subject("s-rej", "c1", kind="business_unit", name="27届秋招", status="rejected"),
            _subject("s-old", "c1", kind="business_unit", name="旧业务", status="retired"),
            _subject("s-manual", "c1", kind="business_unit", name="人工录入", origin="manual"),
        ]
        plan = B.plan_zero_job_changes(existing, matched_company_ids=set(),
                                       known_company_ids={"c1"})
        # rejected / retired 是治理结论；非标题抽取的业务线不归这条链退役（与有岗公司同一条规矩）。
        self.assertEqual((plan["zero"], plan["retire"], plan["company_ids"]), ([], [], []))

    def test_second_run_after_zeroing_plans_nothing(self):
        existing = [_subject("s-co", "c1", name="和睦家医疗", job_count=236),
                    _subject("s-bu", "c1", kind="business_unit", name="养老", job_count=92)]
        first = B.plan_zero_job_changes(existing, matched_company_ids=set(),
                                        known_company_ids={"c1"})
        # 把第一轮的计划落到这两行上，再算一轮：不许再有任何动作，闸门的分母里也不再有这家。
        for row in existing:
            if row["id"] in {r["id"] for r in first["zero"]}:
                row["job_count"] = 0
            if row["id"] in {r["id"] for r in first["retire"]}:
                row.update(status="retired", job_count=0)
        second = B.plan_zero_job_changes(existing, matched_company_ids=set(),
                                         known_company_ids={"c1"})
        self.assertEqual((len(first["zero"]), len(first["retire"])), (1, 1))
        self.assertEqual((second["zero"], second["retire"], second["company_ids"]), ([], [], []))
        self.assertEqual(B.zero_job_holding_companies(existing, {"c1"}), set())

    def test_row_read_twice_is_planned_once(self):
        # 分页读主体时表在变，同一行可能被读到两次：名单和计数都不许翻倍。
        row = _subject("s-co", "c1", job_count=7)
        plan = B.plan_zero_job_changes([row, dict(row)], matched_company_ids=set(),
                                       known_company_ids={"c1"})
        self.assertEqual([r["id"] for r in plan["zero"]], ["s-co"])

    def test_holding_companies_counts_only_those_with_something_to_lose(self):
        existing = [
            _subject("a", "c1", job_count=5),
            _subject("b", "c2", job_count=0),                       # 早就归零：不进分母
            _subject("c", "c2", kind="business_unit", name="x", status="retired"),
            _subject("d", "c3", job_count=0),
            _subject("e", "c3", kind="business_unit", name="y", job_count=0),  # 仍 active 的业务线
            _subject("f", "c-ghost", job_count=9),                  # 画像没读到：判不了，不进分母
        ]
        self.assertEqual(B.zero_job_holding_companies(existing, {"c1", "c2", "c3"}), {"c1", "c3"})


class ZeroJobGateTest(unittest.TestCase):
    def test_normal_share_passes(self):
        # 2026-10-11 真库首轮：卡面数 >0 的 1,349 家里 100 家读出 0 岗（7.4%）。
        self.assertTrue(B.zero_job_reconcile_allowed(100, 1349))

    def test_most_holding_companies_reading_zero_is_blocked(self):
        self.assertFalse(B.zero_job_reconcile_allowed(700, 1349))
        self.assertTrue(B.zero_job_reconcile_allowed(10, 20))      # 正好一半：放行
        self.assertFalse(B.zero_job_reconcile_allowed(11, 20))

    def test_tiny_runs_are_not_judged_by_ratio(self):
        self.assertTrue(B.zero_job_reconcile_allowed(3, 3))


class _FakeSubjectsTable:
    def __init__(self, owner):
        self._owner = owner
        self._log = owner.log
        self._call = None

    def update(self, payload):
        self._call = {"payload": payload, "filters": []}
        return self

    def in_(self, column, values):
        self._call["filters"].append(("in", column, list(values)))
        return self

    def eq(self, column, value):
        self._call["filters"].append(("eq", column, value))
        return self

    def execute(self):
        owner = self._owner
        if owner.fail_on_call is not None and len(self._log) == owner.fail_on_call:
            raise RuntimeError("503")
        self._log.append(self._call)
        ids = next(values for kind, column, values in self._call["filters"]
                   if kind == "in" and column == "id")
        # 与 PostgREST 一样：只回真被改到的行（这里 = 仍然 active 的那些）。
        changed = [i for i in ids if owner.active_ids is None or i in owner.active_ids]
        return mock.Mock(data=[{"id": i} for i in changed])


class _FakeSupabase:
    def __init__(self, active_ids=None, fail_on_call=None):
        self.log = []
        self.active_ids = active_ids
        self.fail_on_call = fail_on_call

    def table(self, name):
        assert name == "insight_subjects", name
        return _FakeSubjectsTable(self)


class ZeroJobApplyTest(unittest.TestCase):
    def test_zeroing_keeps_status_and_last_seen_and_only_touches_active_rows(self):
        sb = _FakeSupabase()
        plan = {"zero": [{"id": "s-co"}], "retire": [{"id": "s-bu"}], "company_ids": ["c1"]}
        self.assertEqual(B.apply_zero_job_plan(sb, plan, "NOW"), (1, 1))
        zero_call, retire_call = sb.log
        # 归零不碰 status / last_seen_at：last_seen_at 的含义是「上次看到它有岗」，归零那一刻不是。
        self.assertEqual(zero_call["payload"], {"job_count": 0, "updated_at": "NOW"})
        self.assertEqual(retire_call["payload"],
                         {"status": "retired", "job_count": 0, "updated_at": "NOW"})
        for call, ids in ((zero_call, ["s-co"]), (retire_call, ["s-bu"])):
            self.assertIn(("in", "id", ids), call["filters"])
            # 读计划到写库之间，后台可能刚把某条判成 rejected：只动仍然 active 的行，不覆盖治理结论。
            self.assertIn(("eq", "status", "active"), call["filters"])

    def test_empty_plan_sends_nothing(self):
        sb = _FakeSupabase()
        self.assertEqual(B.apply_zero_job_plan(sb, {"zero": [], "retire": []}, "NOW"), (0, 0))
        self.assertEqual(sb.log, [])

    def test_every_id_is_sent_across_batches(self):
        sb = _FakeSupabase()
        plan = {"zero": [{"id": f"s{i}"} for i in range(5)], "retire": []}
        self.assertEqual(B.apply_zero_job_plan(sb, plan, "NOW", batch=2), (5, 0))
        sent = [i for call in sb.log for kind, column, ids in call["filters"]
                if kind == "in" for i in ids]
        self.assertEqual(sent, ["s0", "s1", "s2", "s3", "s4"])
        self.assertEqual(len(sb.log), 3)

    def test_count_is_rows_actually_changed_not_rows_planned(self):
        # 计划里两行，其中一行在读计划之后被后台改成了 rejected：库里只动了一行，就只报一行。
        sb = _FakeSupabase(active_ids={"s-a"})
        plan = {"zero": [{"id": "s-a"}, {"id": "s-b"}], "retire": []}
        self.assertEqual(B.apply_zero_job_plan(sb, plan, "NOW"), (1, 0))

    def test_partial_progress_survives_a_mid_way_failure(self):
        # 归零那一批写成了、退役那一批抛错：调用方必须还拿得到「已经归零 2 个」。
        sb = _FakeSupabase(fail_on_call=1)
        plan = {"zero": [{"id": "s-a"}, {"id": "s-b"}], "retire": [{"id": "s-bu"}]}
        done = {}
        with self.assertRaises(RuntimeError):
            B.apply_zero_job_plan(sb, plan, "NOW", done=done)
        self.assertEqual(done, {"zero": 2, "retire": 0})


class ZeroJobMainTest(unittest.TestCase):
    """真跑 main()，只把读写库的边界换掉。"""

    def _run_main(self, argv, *, profiles, job_rows, existing, fetch_error=None,
                  zero_error=None):
        def fake_fetch_jobs(company=""):
            if fetch_error:
                raise fetch_error
            return [row for row in job_rows if not company or row["company"] == company]

        def fake_apply(sb, plan, now):
            return len(plan["insert"]), len(plan["update"]), len(plan["retire"])

        def fake_zero(sb, plan, now, done=None):
            done = {} if done is None else done
            done["zero"] = len(plan["zero"])
            if zero_error:       # 归零那一批已经写成，退役那一批抛错
                raise zero_error
            done["retire"] = len(plan["retire"])
            return done["zero"], done["retire"]

        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            patch = lambda target, name, **kw: stack.enter_context(  # noqa: E731
                mock.patch.object(target, name, **kw))
            stack.enter_context(mock.patch.dict(os.environ, {}, clear=False))
            for key in ("BU_CREATE_PROFILES", "BU_MIN_JOBS", "BU_PROFILE_MIN_JOBS"):
                os.environ.pop(key, None)
            patch(sys, "argv", new=["bu_extract.py", *argv])
            self.sb = mock.MagicMock()
            patch(B.db, "get_supabase", return_value=self.sb)
            patch(B.db, "fetch_all_rows", return_value=profiles)
            patch(B, "fetch_active_jobs", side_effect=fake_fetch_jobs)
            patch(B, "fetch_existing_subjects", return_value=existing)
            apply = patch(B, "apply_plan", side_effect=fake_apply)
            zero = patch(B, "apply_zero_job_plan", side_effect=fake_zero)
            record = patch(B.ops_runs, "record_ops_run")
            stack.enter_context(contextlib.redirect_stdout(out))
            self.mocks = (apply, zero, record)
            B.main()
        return apply, zero, record, out.getvalue()

    PROFILES = [
        {"id": "c-live", "company": "有岗公司", "aliases": []},
        {"id": "c-gone", "company": "没岗公司", "aliases": []},
    ]
    EXISTING = [
        _subject("s-live", "c-live", name="有岗公司", job_count=3),
        _subject("s-gone", "c-gone", name="没岗公司", job_count=86),
        _subject("s-gone-bu", "c-gone", kind="business_unit", name="养老", job_count=30),
    ]
    JOBS = [{"company": "有岗公司", "title": "后端工程师"}] * 3

    @staticmethod
    def _zero_plan(zero):
        return zero.call_args.args[1]

    @staticmethod
    def _ledger(record):
        return record.call_args.args[2]

    def test_full_scan_zeroes_the_company_without_jobs_and_keeps_the_other(self):
        apply, zero, record, _ = self._run_main(
            [], profiles=self.PROFILES, job_rows=self.JOBS, existing=self.EXISTING)
        plan = self._zero_plan(zero)
        self.assertEqual([row["id"] for row in plan["zero"]], ["s-gone"])
        self.assertEqual([row["id"] for row in plan["retire"]], ["s-gone-bu"])
        # 另一个方向：有岗的那家照常对账，没被当成 0 岗。
        self.assertEqual(apply.call_count, 1)
        touched = {row["id"] for row in apply.call_args.args[1]["update"]}
        self.assertEqual(touched, {"s-live"})
        ledger = self._ledger(record)
        self.assertEqual(ledger["jobs_scanned"], 3)
        self.assertEqual(ledger["companies_scanned"], 1)
        self.assertEqual(ledger["companies_zero_jobs"], 1)
        self.assertEqual(ledger["zero_job_zeroed"], 1)
        self.assertEqual(ledger["zero_job_retired"], 1)
        self.assertEqual(ledger["retired"], 1)
        self.assertEqual(ledger["zero_job_blocked"], 0)
        self.assertEqual(record.call_args.kwargs["status"], "success")

    def test_company_matched_only_by_normalized_name_is_not_zeroed(self):
        # 2026-10-10 真库的协鑫：画像名「协鑫」，岗挂在「协鑫集团有限公司」下。按精确等号数是 0 岗，
        # 按本模块自己的归属（精确名优先、归一名兜底）是 5 岗——归零必须用后者。
        profiles = [{"id": "c-gcl", "company": "协鑫", "aliases": []}]
        existing = [_subject("s-gcl", "c-gcl", name="协鑫", job_count=5)]
        jobs = [{"company": "协鑫集团有限公司", "title": "工艺工程师"}] * 5
        _, zero, record, _ = self._run_main([], profiles=profiles, job_rows=jobs, existing=existing)
        zero.assert_not_called()
        self.assertEqual(self._ledger(record)["companies_zero_jobs"], 0)

    def test_company_flag_never_treats_unscanned_companies_as_zero(self):
        apply, zero, record, printed = self._run_main(
            ["--company", "有岗公司"], profiles=self.PROFILES, job_rows=self.JOBS,
            existing=self.EXISTING)
        zero.assert_not_called()
        # 没量过不等于 0：只处理一部分公司的跑法，台账里不出现 0 岗对账的键。
        self.assertNotIn("companies_zero_jobs", self._ledger(record))
        self.assertNotIn("zero_job_zeroed", self._ledger(record))
        self.assertIn("不做 0 岗对账", printed)

    def test_limit_flag_never_treats_unscanned_companies_as_zero(self):
        profiles = self.PROFILES + [{"id": "c-b", "company": "乙有岗公司", "aliases": []}]
        existing = self.EXISTING + [_subject("s-b", "c-b", name="乙有岗公司", job_count=2)]
        jobs = self.JOBS + [{"company": "乙有岗公司", "title": "前端工程师"}] * 2
        apply, zero, record, _ = self._run_main(
            ["--limit", "1"], profiles=profiles, job_rows=jobs, existing=existing)
        # 被 --limit 截掉的那家有岗；真 0 岗的那家这一轮也不动（只处理了一部分公司）。
        zero.assert_not_called()
        self.assertEqual(apply.call_count, 1)

    def test_fetch_failure_aborts_before_any_write(self):
        with self.assertRaises(RuntimeError):
            self._run_main([], profiles=self.PROFILES, job_rows=self.JOBS,
                           existing=self.EXISTING, fetch_error=RuntimeError("statement timeout"))
        apply, zero, record = self.mocks
        # 「没取到」不是「取到 0 个」：一行都不许写。
        apply.assert_not_called()
        zero.assert_not_called()
        record.assert_not_called()

    def _fleet(self, *, gone, healthy, already_zero=0):
        profiles, existing, jobs = [], [], []
        for kind, count in (("gone", gone), ("ok", healthy), ("dead", already_zero)):
            for i in range(count):
                key = f"{kind}{i:02d}公司"
                profiles.append({"id": f"c-{kind}{i}", "company": key, "aliases": []})
                existing.append(_subject(f"s-{kind}{i}", f"c-{kind}{i}", name=key,
                                         job_count=0 if kind == "dead" else 7))
                if kind == "ok":
                    jobs.append({"company": key, "title": "工程师"})
        return dict(profiles=profiles, existing=existing, job_rows=jobs)

    def test_most_holding_companies_reading_zero_blocks_the_zeroing(self):
        # 卡面数 >0 的 25 家里 20 家同时读出 0 岗：更像岗位库出了问题。
        # 30 家早就归零的公司不进分母——算进去是 20/55，闸门形同虚设。
        apply, zero, record, printed = self._run_main(
            [], **self._fleet(gone=20, healthy=5, already_zero=30))
        zero.assert_not_called()
        self.assertEqual(apply.call_count, 5)      # 有岗的 5 家照常对账
        ledger = self._ledger(record)
        self.assertEqual(ledger["zero_job_blocked"], 20)
        self.assertEqual(ledger["zero_job_zeroed"], 0)
        # 台账必须是 failed：按原算法 0 失败 = success，闸门拦过这件事就没人知道。
        self.assertEqual(record.call_args.kwargs["status"], "failed")
        self.assertIn("::warning::", printed)

    def test_few_companies_reading_zero_passes_the_gate(self):
        # 名下还有数的 80 家里 20 家读出 0 岗（25%）：放行。60 家早就归零的既不进分子也不进分母——
        # 把它们算进分子是 80/80，把分母接成「本轮要归零的公司数」是 20/20，两种接错都会在这里红
        #（本轮要归零的必须 ≥20 家，否则后一种接错会被「小样本不看比例」放过去）。
        apply, zero, record, _ = self._run_main(
            [], **self._fleet(gone=20, healthy=60, already_zero=60))
        zero.assert_called_once()
        self.assertEqual(len(self._zero_plan(zero)["company_ids"]), 20)
        ledger = self._ledger(record)
        self.assertEqual(ledger["zero_job_zeroed"], 20)
        self.assertEqual(ledger["zero_job_blocked"], 0)
        self.assertEqual(ledger["companies_zero_jobs"], 80)   # 存量：含早就归零的 60 家
        self.assertEqual(record.call_args.kwargs["status"], "success")

    def test_subject_whose_profile_was_not_read_is_reported_not_zeroed(self):
        existing = self.EXISTING + [_subject("s-ghost", "c-ghost", name="画像没读到", job_count=9)]
        _, zero, _, printed = self._run_main(
            [], profiles=self.PROFILES, job_rows=self.JOBS, existing=existing)
        self.assertNotIn("s-ghost", {row["id"] for row in self._zero_plan(zero)["zero"]})
        self.assertIn("1 家公司有 active 主体但画像没读到", printed)

    def test_empty_jobs_table_does_not_zero_every_company(self):
        apply, zero, record, _ = self._run_main([], **self._fleet(gone=40, healthy=0))
        zero.assert_not_called()
        apply.assert_not_called()
        self.assertEqual(self._ledger(record)["zero_job_blocked"], 40)
        self.assertEqual(record.call_args.kwargs["status"], "failed")

    def test_dry_run_reports_the_plan_and_writes_nothing(self):
        apply, zero, record, printed = self._run_main(
            ["--dry-run"], profiles=self.PROFILES, job_rows=self.JOBS, existing=self.EXISTING)
        apply.assert_not_called()
        zero.assert_not_called()
        record.assert_not_called()
        # 读都走被换掉的函数，所以 dry-run 下 supabase 本体一次都不该被碰（直接在分支里写库也会在这里红）。
        self.sb.table.assert_not_called()
        self.assertIn("没岗公司：0 个在招岗，公司主体在招数 86 → 0；退役业务线 养老(30)", printed)
        self.assertIn("dry-run：1 家公司 0 个在招岗，其中 1 家名下还有数", printed)

    def test_dry_run_says_zero_out_loud_when_nothing_would_change(self):
        existing = [_subject("s-live", "c-live", name="有岗公司", job_count=3)]
        _, zero, _, printed = self._run_main(
            ["--dry-run"], profiles=self.PROFILES, job_rows=self.JOBS, existing=existing)
        self.sb.table.assert_not_called()
        self.assertIn("dry-run：0 家公司 0 个在招岗，其中 0 家名下还有数", printed)

    def test_failed_zeroing_write_is_counted_and_reaches_the_ledger(self):
        apply, zero, record, printed = self._run_main(
            [], profiles=self.PROFILES, job_rows=self.JOBS, existing=self.EXISTING,
            zero_error=RuntimeError("503"))
        zero.assert_called_once()
        ledger = self._ledger(record)
        self.assertEqual(ledger["failed"], 1)
        # 归零那一批已经落库：台账照实记 1，不能因为后面抛错就记成 0。
        self.assertEqual(ledger["zero_job_zeroed"], 1)
        self.assertEqual(ledger["zero_job_retired"], 0)
        self.assertEqual(ledger["retired"], 0)
        self.assertIn("归零失败", printed)
        self.assertIn("503", printed)


class SegmentedTitleNoiseTest(unittest.TestCase):
    """入库保留完整标题（2026-10-10）后新冒出来的两类假业务线：学历前缀、校招场次。

    拿 live 抓到的 966 个源的原始标题预演，新标题比旧标题多抽出 63 个业务线、少 0 个；
    多出来的绝大多数是字节的真业务线（TikTok研发 / 芯片研发 / 飞书商业化 / 火山引擎…），下面这几个不是。
    """

    def test_degree_prefix_and_campus_session_are_noise(self):
        for token in ("博士", "硕士", "本科", "“大城市”专场"):
            with self.subTest(token=token):
                self.assertTrue(B.is_noise(token), token)

    def test_real_business_units_after_spaced_dash_survive(self):
        self.assertIn("飞书商业化", B.extract_candidates("渠道城市经理（杭州） - 飞书商业化"))
        # 学历词只做全等判断：「博士后工作站」这种含学历词的真部门名不受影响。
        for token in ("飞书商业化", "芯片研发", "TikTok研发", "火山引擎", "博士后工作站"):
            with self.subTest(token=token):
                self.assertFalse(B.is_noise(token), token)
