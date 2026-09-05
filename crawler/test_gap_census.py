import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gap_census as gc


NOW = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)


def _company(name="甲公司", pattern="%甲公司%", industry="金融"):
    return {"name": name, "pattern": pattern, "industries": [industry]}


class ClassifyCompanyTest(unittest.TestCase):
    def test_healthy_company_wins_over_previous_failure(self):
        row = gc.classify_company(
            _company(),
            [{"company": "甲公司集团", "active_total": 3, "healthy": 1}],
            [],
            {"state": "no_active_jobs", "attempts": 2},
        )
        self.assertEqual(row["state"], "healthy")
        self.assertEqual(row["evidence"]["healthy_jobs"], 1)

    def test_enabled_source_without_jobs_is_no_active_jobs(self):
        row = gc.classify_company(
            _company(), [], [{"company": "甲公司", "enabled": True, "id": "s1"}], None
        )
        self.assertEqual(row["state"], "no_active_jobs")
        self.assertEqual(row["source_id"], "s1")

    def test_disabled_source_only_is_unknown(self):
        row = gc.classify_company(
            _company(), [], [{"company": "甲公司", "enabled": False, "id": "s1"}], None
        )
        self.assertEqual(row["state"], "unknown")
        self.assertIsNone(row["source_id"])

    def test_company_without_source_is_unknown(self):
        row = gc.classify_company(_company(), [], [], None)
        self.assertEqual(row["state"], "unknown")

    def test_first_seen_empty_source_is_due_now_not_stranded(self):
        row = gc.classify_company(
            _company(), [], [{"company": "甲公司", "enabled": True, "id": "s1"}], None
        )
        scheduled = gc.schedule_initial_retry(row, NOW)
        self.assertEqual(scheduled["next_retry_at"], NOW.isoformat())

    def test_alias_matches_jobs_and_sources_recorded_under_the_english_name(self):
        """库里用英文名记着这家公司时，别名要能把源和岗都认回来。

        2026-09-04 事故：壳牌库里记作 `Shell`，中文 pattern 匹配不上 → 判「零源缺口」
        → 插了第二条源（同一个 Workday 站点仅大小写不同）→ 同一个岗在库里存了两行。
        **「有岗但指标显示 0」比「真没岗」更危险：它会驱动人去重复补源。**
        """
        company = {**_company("大陆集团", "%大陆集团%", "汽车/出行"),
                   "aliases": ["%Continental%"]}
        row = gc.classify_company(
            company,
            [{"company": "Continental", "active_total": 425, "healthy": 425}],
            [{"company": "Continental", "enabled": True, "id": "s-continental"}],
            None,
        )
        self.assertEqual(row["state"], "healthy")
        self.assertEqual(row["evidence"]["healthy_jobs"], 425)
        self.assertEqual(row["evidence"]["matched_job_companies"], ["Continental"])
        self.assertEqual(row["source_id"], "s-continental")
        # 台账要能自己解释「为什么这家不再是零源」，否则下一个人还是会去搜中文名、再插一条源
        self.assertEqual(row["evidence"]["matched_alias_patterns"], ["%Continental%"])

    def test_alias_only_source_lifts_zero_source_company_out_of_unknown(self):
        row = gc.classify_company(
            {**_company("壳牌", "%壳牌%", "能源/化工"), "aliases": ["%Shell%"]},
            [],
            [{"company": "Shell", "enabled": True, "id": "s-shell"}],
            None,
        )
        self.assertEqual(row["state"], "no_active_jobs")  # 有源没岗，不再是「零源 unknown」
        self.assertEqual(row["source_id"], "s-shell")

    def test_evidence_records_the_other_scope_so_zero_here_is_not_read_as_zero_supply(self):
        """「这个范围里没岗」≠「这家公司没岗」。

        大陆集团国内 73 个、海外还有 352 个；创始人 2026-09-05 拍板普查只数本 scope 的岗，
        所以台账必须同时记下另一个范围的数，否则下一个人看到国内 73 会以为公司快没岗了。
        """
        row = gc.classify_company(
            {**_company("大陆集团", "%大陆集团%", "汽车/出行"), "aliases": ["%Continental%"]},
            [{"company": "Continental", "active_total": 73, "healthy": 73,
              "other_scope_healthy": 352}],
            [], None,
        )
        self.assertEqual(row["evidence"]["healthy_jobs"], 73)
        self.assertEqual(row["evidence"]["other_scope_healthy_jobs"], 352)

    def test_other_scope_is_null_not_zero_when_the_column_is_absent(self):
        """拿不到那一列时写 null，不写 0 —— 「不知道」和「另一个范围也没岗」是两回事。"""
        row = gc.classify_company(
            _company(), [{"company": "甲公司集团", "active_total": 3, "healthy": 3}], [], None
        )
        self.assertIsNone(row["evidence"]["other_scope_healthy_jobs"])

    def test_without_aliases_matching_is_byte_for_byte_unchanged(self):
        """没写别名的公司（清单里 300+ 家都是）行为必须与加别名前完全一致。"""
        row = gc.classify_company(
            _company(), [{"company": "Continental", "active_total": 9, "healthy": 9}], [], None
        )
        self.assertEqual(row["state"], "unknown")
        self.assertEqual(row["evidence"]["healthy_jobs"], 0)
        self.assertEqual(row["evidence"]["matched_alias_patterns"], [])

    def test_alias_that_matches_nothing_is_not_reported_as_evidence(self):
        row = gc.classify_company(
            {**_company(), "aliases": ["%NeverSeen%"]},
            [{"company": "甲公司集团", "active_total": 3, "healthy": 1}], [], None,
        )
        self.assertEqual(row["state"], "healthy")
        self.assertEqual(row["evidence"]["matched_alias_patterns"], [])

    def test_parent_portal_brand_with_three_healthy_titles_is_healthy_and_not_queued(self):
        company = {
            **_company("网易云音乐", "%网易云音乐%", "传媒/文娱"),
            "parentPattern": "%网易%",
            "brandTokens": ["云音乐"],
        }
        row = gc.classify_company(
            company,
            [{
                "company": "网易集团",
                "active_total": 41,
                "healthy": 41,
                "brand_rollups": {
                    "%网易云音乐%": {"active_total": 41, "healthy": 3}
                },
            }],
            [],
        )
        queue = gc.plan_queue(
            [row], {"传媒/文娱"}, set(), {"传媒/文娱": 1.0}, now=NOW, cap=20
        )
        self.assertEqual(row["state"], "healthy")
        self.assertEqual(row["evidence"]["parent_portal_healthy_jobs"], 3)
        self.assertEqual(queue, [])

    def test_parent_portal_brand_with_two_healthy_titles_stays_in_queue(self):
        company = {
            **_company("网易云音乐", "%网易云音乐%", "传媒/文娱"),
            "parentPattern": "%网易%",
            "brandTokens": ["云音乐"],
        }
        row = gc.classify_company(
            company,
            [{
                "company": "网易集团",
                "active_total": 41,
                "healthy": 41,
                "brand_rollups": {
                    "%网易云音乐%": {"active_total": 2, "healthy": 2}
                },
            }],
            [],
        )
        queue = gc.plan_queue(
            [row], {"传媒/文娱"}, set(), {"传媒/文娱": 0.0}, now=NOW, cap=20
        )
        self.assertEqual(row["state"], "unknown")
        self.assertEqual([item["company"] for item in queue], ["网易云音乐"])

    def test_brand_rollup_query_is_single_scan_and_title_only(self):
        companies = [{
            **_company("网易云音乐", "%网易云音乐%", "传媒/文娱"),
            "parentPattern": "%网易%",
            "brandTokens": ["云音乐"],
        }]
        with mock.patch.object(gc.jobs_db, "fetch_all", return_value=[]) as fetch:
            self.assertEqual(gc.fetch_job_aggregates(object(), companies), [])
        fetch.assert_called_once()
        sql = fetch.call_args.args[1].lower()
        self.assertIn("title ilike any", sql)
        self.assertIn("company not ilike", sql)
        self.assertNotIn("summary ilike", sql)

    def test_load_companies_preserves_optional_brand_fields(self):
        with mock.patch.object(gc.must_apply, "by_industry", return_value={
            "传媒/文娱": [{
                "name": "网易云音乐",
                "pattern": "%网易云音乐%",
                "parentPattern": "%网易%",
                "brandTokens": ["云音乐"],
            }]
        }):
            loaded = gc.load_companies("domestic")
        self.assertEqual(loaded[0]["parentPattern"], "%网易%")
        self.assertEqual(loaded[0]["brandTokens"], ["云音乐"])

    def test_load_companies_carries_aliases_and_skips_blank_ones(self):
        with mock.patch.object(gc.must_apply, "by_industry", return_value={
            "能源/化工": [{"name": "壳牌", "pattern": "%壳牌%", "aliases": ["%Shell%", " "]}],
            "汽车/出行": [{"name": "大陆集团", "pattern": "%大陆集团%"}],
        }):
            loaded = {row["name"]: row for row in gc.load_companies("domestic")}
        self.assertEqual(loaded["壳牌"]["aliases"], ["%Shell%"])
        self.assertNotIn("aliases", loaded["大陆集团"])  # 没别名的公司不该凭空长出字段


class JobAggregateScopeTest(unittest.TestCase):
    """岗位聚合只数本 scope 的岗（2026-09-05 创始人拍板的口径变更）。

    改之前两份清单共用不分 scope 的合计：海外清单的星巴克显示 1,920 个健康岗（实际全是中国
    门店岗）、国内清单的松下显示 226 个（实际 18,318 个岗全在海外）。
    """

    COMPANY = {"name": "网易云音乐", "pattern": "%网易云音乐%",
               "parentPattern": "%网易%", "brandTokens": ["云音乐"]}

    def test_scope_is_bound_as_a_parameter_not_interpolated(self):
        sql, params, _rules = gc._job_aggregate_query([self.COMPANY], "overseas")
        self.assertEqual(params["scope"], "overseas")
        self.assertNotIn("'overseas'", sql)  # 走参数绑定，不拼字符串
        self.assertIn("count(*) filter (where job_scope = %(scope)s) as active_total", sql)

    def test_brand_rollup_columns_are_scope_filtered_too(self):
        """父公司门户的 rollup 不跟着过滤，海外岗会从后门漏进国内覆盖。"""
        sql, _params, rules = gc._job_aggregate_query([self.COMPANY], "domestic")
        self.assertEqual(len(rules), 1)
        self.assertEqual(sql.count("and job_scope = %(scope)s"), 2)  # rollup 的 active + healthy 各一

    def test_other_scope_column_uses_the_complement_not_a_hardcoded_scope(self):
        sql, _params, _rules = gc._job_aggregate_query([], "overseas")
        self.assertIn("where job_scope <> %(scope)s", sql)


class QueuePlanningTest(unittest.TestCase):
    def test_never_attempted_company_runs_before_old_retry(self):
        rows = [
            {"company": "老失败", "industries": ["金融"], "state": "unknown", "attempts": 30},
            {"company": "新公司", "industries": ["金融"], "state": "unknown", "attempts": 0},
        ]
        queue = gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=2)
        self.assertEqual([row["company"] for row in queue], ["新公司", "老失败"])

    def test_unknown_with_future_retry_is_not_eligible(self):
        rows = [{
            "company": "未到期", "industries": ["金融"], "state": "unknown", "attempts": 30,
            "next_retry_at": (NOW + timedelta(days=1)).isoformat(),
        }]
        queue = gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20)
        self.assertEqual(queue, [])

    def test_zero_cap_returns_no_rows(self):
        rows = [{"company": "新公司", "industries": ["金融"], "state": "unknown"}]
        self.assertEqual(
            gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=0),
            [],
        )

    def test_industry_quota_defers_excess_then_backfills_when_needed(self):
        rows = [
            {"company": "金%02d" % index, "industries": ["金融"], "state": "unknown"}
            for index in range(5)
        ] + [
            {"company": "教育%02d" % index, "industries": ["教育"], "state": "unknown"}
            for index in range(3)
        ]
        queue = gc.plan_queue(
            rows, {"金融", "教育"}, set(), {"金融": 0.1, "教育": 0.2}, now=NOW, cap=5
        )
        self.assertEqual(sum(row["industries"][0] == "金融" for row in queue), 3)
        self.assertEqual(sum(row["industries"][0] == "教育" for row in queue), 2)

        only_finance = gc.plan_queue(
            rows[:5], {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=5
        )
        self.assertEqual(len(only_finance), 5)

    def test_target_industry_then_user_wanted_then_low_coverage(self):
        rows = [
            {"company": "非目标", "industries": ["互联网/科技"], "state": "unknown"},
            {"company": "用户点名", "industries": ["金融"], "state": "unknown"},
            {"company": "低覆盖", "industries": ["教育"], "state": "unknown"},
            {"company": "普通目标", "industries": ["金融"], "state": "unknown"},
        ]
        queue = gc.plan_queue(
            rows,
            target_industries={"金融", "教育"},
            user_wanted={"用户点名"},
            industry_coverage={"金融": 0.4, "教育": 0.2, "互联网/科技": 0.1},
            now=NOW,
            cap=20,
        )
        self.assertEqual(
            [r["company"] for r in queue],
            ["用户点名", "低覆盖", "普通目标", "非目标"],
        )

    def test_manual_states_without_retry_never_enter_queue(self):
        rows = [
            {"company": "人工", "industries": ["金融"], "state": "manual_review", "next_retry_at": None},
            {"company": "治理", "industries": ["金融"], "state": "governance_candidate", "next_retry_at": None},
            {"company": "到期", "industries": ["金融"], "state": "no_active_jobs",
             "next_retry_at": (NOW - timedelta(seconds=1)).isoformat()},
            {"company": "未来", "industries": ["金融"], "state": "no_active_jobs",
             "next_retry_at": (NOW + timedelta(days=1)).isoformat()},
        ]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20
        )
        self.assertEqual([r["company"] for r in queue], ["到期"])

    def test_cap_is_applied_after_sorting(self):
        rows = [
            {"company": f"C{i:02d}", "industries": ["金融"], "state": "unknown"}
            for i in range(30)
        ]
        queue = gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=7)
        self.assertEqual(len(queue), 7)
        self.assertEqual(queue[0]["company"], "C00")


if __name__ == "__main__":
    unittest.main()


class RevalidateLaneTest(unittest.TestCase):
    """退避复验车道：adapter 修好后，受益公司不该干等一个月才被重测。

    实证（2026-09-05）：埃斯顿 8-28 判 no_stable_jd、退避到 9-30，而 8-27 落地的 beisen
    改动当天就能从同一个 URL 抓到 63 个健康岗——期间 8 次定时跑一次都没复测它。
    """

    def _row(self, company, state, *, days_ago, retry_days):
        return {
            "company": company,
            "industries": ["金融"],
            "state": state,
            "last_attempt_at": (NOW - timedelta(days=days_ago)).isoformat(),
            "next_retry_at": (NOW + timedelta(days=retry_days)).isoformat(),
        }

    def test_spare_capacity_revalidates_longest_waiting_first(self):
        rows = [
            self._row("等最久", "no_stable_jd", days_ago=30, retry_days=25),
            self._row("等中等", "no_stable_jd", days_ago=10, retry_days=25),
            self._row("刚跑过", "no_stable_jd", days_ago=1, retry_days=25),
        ]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20,
            revalidate_slots=2,
        )
        self.assertEqual([r["company"] for r in queue], ["等最久", "等中等"])

    def test_due_rows_keep_priority_over_revalidation(self):
        rows = [
            self._row("退避中", "no_stable_jd", days_ago=30, retry_days=25),
            {"company": "已到期", "industries": ["金融"], "state": "no_stable_jd",
             "next_retry_at": (NOW - timedelta(seconds=1)).isoformat()},
        ]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20,
            revalidate_slots=5,
        )
        self.assertEqual(queue[0]["company"], "已到期")
        self.assertEqual(len(queue), 2)

    def test_revalidation_never_exceeds_cap(self):
        rows = [
            {"company": f"到期{i}", "industries": ["金融"], "state": "unknown"}
            for i in range(4)
        ] + [self._row("退避中", "no_stable_jd", days_ago=99, retry_days=25)]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=4,
            revalidate_slots=3,
        )
        self.assertEqual(len(queue), 4)
        self.assertNotIn("退避中", [r["company"] for r in queue])

    def test_terminal_and_manual_states_are_never_revalidated(self):
        """治理/登录墙/反爬是「人工或对方的问题」，不会因我们改 adapter 而变化。"""
        rows = [
            self._row("治理", "governance_candidate", days_ago=99, retry_days=25),
            self._row("登录墙", "login_wall", days_ago=99, retry_days=25),
            self._row("反爬", "anti_bot", days_ago=99, retry_days=25),
            self._row("人工", "manual_review", days_ago=99, retry_days=25),
            self._row("健康", "healthy", days_ago=99, retry_days=25),
        ]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20,
            revalidate_slots=5,
        )
        self.assertEqual(queue, [])

    def test_slots_zero_disables_the_lane(self):
        rows = [self._row("退避中", "no_stable_jd", days_ago=99, retry_days=25)]
        self.assertEqual(
            gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1},
                          now=NOW, cap=20, revalidate_slots=0),
            [],
        )

    def test_ignore_backoff_still_wins_and_does_not_double_count(self):
        rows = [self._row("点名", "no_stable_jd", days_ago=99, retry_days=25)]
        queue = gc.plan_queue(
            rows, {"金融"}, set(), {"金融": 0.1}, now=NOW, cap=20,
            ignore_backoff=True, revalidate_slots=3,
        )
        self.assertEqual([r["company"] for r in queue], ["点名"])

    def test_never_attempted_rows_are_not_treated_as_long_waiting(self):
        """last_attempt_at 缺失 = 排了期但没跑过，不是「等了很久」，退避照常生效。"""
        rows = [{
            "company": "排期未跑", "industries": ["金融"], "state": "no_stable_jd",
            "next_retry_at": (NOW + timedelta(days=1)).isoformat(),
        }]
        self.assertEqual(
            gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1},
                          now=NOW, cap=20, revalidate_slots=3),
            [],
        )

    def test_recent_attempt_is_not_revalidated(self):
        rows = [self._row("刚跑过", "no_stable_jd", days_ago=2, retry_days=25)]
        self.assertEqual(
            gc.plan_queue(rows, {"金融"}, set(), {"金融": 0.1},
                          now=NOW, cap=20, revalidate_slots=3),
            [],
        )
