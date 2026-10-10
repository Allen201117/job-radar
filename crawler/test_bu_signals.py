import contextlib
import io
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import bu_extract
import bu_signals as S

NOW = datetime(2026, 9, 3, tzinfo=timezone.utc)


def job(days_ago=1, **kw):
    row = {
        "title": "后端开发工程师",
        "location": "北京",
        "experience": None,
        "education": None,
        "salary_text": None,
        "recruitment_category": None,
        "first_seen_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }
    row.update(kw)
    return row


class ParsersTest(unittest.TestCase):
    def test_min_years_covers_normalizer_output_shapes(self):
        # normalizer.extract_experience 只产出这几种形态
        self.assertEqual(S.parse_min_years("3-5年"), 3.0)
        self.assertEqual(S.parse_min_years("5年+"), 5.0)
        self.assertEqual(S.parse_min_years("12年+"), 12.0)
        self.assertEqual(S.parse_min_years("应届/不限"), 0.0)

    def test_min_years_abstains_instead_of_guessing_zero(self):
        for value in (None, "", "面议", "见JD"):
            self.assertIsNone(S.parse_min_years(value), value)

    def test_salary_only_accepts_explicit_ranges(self):
        self.assertEqual(S.parse_salary_mid_k("15-30K"), 22.5)
        self.assertEqual(S.parse_salary_mid_k("15k-25k/月"), 20.0)
        self.assertEqual(S.parse_salary_mid_k("15000-30000元"), 22.5)

    def test_salary_abstains_on_ambiguous_units(self):
        # 「万」有年/月歧义 —— 宁可少一条也不进垃圾数据（与 lib/insight-derive 同口径）
        for value in ("20-40万", "面议", "薪资优厚", None, "30K"):
            self.assertIsNone(S.parse_salary_mid_k(value), value)

    def test_distribution_sorted_and_shares_sum_to_100(self):
        dist = S.distribution(["北京", "北京", "上海", None, ""])
        self.assertEqual(dist[0]["key"], "北京")
        self.assertEqual(dist[0]["count"], 2)
        self.assertAlmostEqual(sum(d["share"] for d in dist), 100.0, places=1)


class SampleGateTest(unittest.TestCase):
    """spec §1.5 硬规则：样本不足即整条省略，不显示 0、不做小样本百分比。"""

    def test_company_below_floor_produces_nothing(self):
        self.assertEqual(
            S.compute_metrics([job() for _ in range(S.MIN_COMPANY - 1)],
                              kind="company", subject_name="某公司", now=NOW),
            [],
        )

    def test_business_unit_uses_higher_floor(self):
        jobs = [job() for _ in range(S.MIN_BU - 1)]
        self.assertEqual(
            S.compute_metrics(jobs, kind="business_unit", subject_name="飞书", now=NOW), [])
        jobs.append(job())
        self.assertTrue(
            S.compute_metrics(jobs, kind="business_unit", subject_name="飞书", now=NOW))

    def test_thin_field_is_omitted_not_zeroed(self):
        # 20 个岗里只有 3 个写了学历 → 不出 edu_requirement_mode，而不是出一个 15%
        jobs = [job(education="本科") for _ in range(3)] + [job() for _ in range(17)]
        keys = {m["metric_key"] for m in
                S.compute_metrics(jobs, kind="company", subject_name="某公司", now=NOW)}
        self.assertNotIn("edu_requirement_mode", keys)
        self.assertIn("hiring_volume_30d", keys)

    def test_every_metric_carries_sample_n(self):
        jobs = [job(education="本科", experience="3-5年", salary_text="15-30K",
                    recruitment_category="社招") for _ in range(20)]
        metrics = S.compute_metrics(jobs, kind="company", subject_name="某公司", now=NOW,
                                    functions=["研发"] * 20)
        self.assertTrue(metrics)
        for m in metrics:
            self.assertGreaterEqual(m["sample_size"], 1, m["metric_key"])
            self.assertIn("sample_n", m["payload"])
            # 正文必须把样本量写给用户看（spec §1.5 规则 1）
            self.assertIn("基于", m["content"], m["metric_key"])


class ContentComplianceTest(unittest.TestCase):
    """正文必须过 lib/insight-verification 的绝对化措辞禁令。"""

    BANNED = ("必然", "肯定", "都是", "最好", "最差")

    def test_no_absolute_wording(self):
        jobs = [job(education="硕士", experience="5年+", salary_text="20-40K",
                    recruitment_category="校招") for _ in range(30)]
        metrics = S.compute_metrics(jobs, kind="company", subject_name="某公司", now=NOW,
                                    functions=["研发"] * 30, bu_count=3)
        self.assertTrue(metrics)
        for m in metrics:
            for word in self.BANNED:
                self.assertNotIn(word, m["content"], f"{m['metric_key']} 含禁用词 {word}")


class FunctionAbstentionTest(unittest.TestCase):
    def test_function_share_absent_when_classifier_abstains(self):
        jobs = [job() for _ in range(20)]
        keys = {m["metric_key"] for m in S.compute_metrics(
            jobs, kind="company", subject_name="某公司", now=NOW, functions=None)}
        self.assertNotIn("function_share", keys)

    def test_function_share_present_when_classifier_works(self):
        jobs = [job() for _ in range(20)]
        keys = {m["metric_key"] for m in S.compute_metrics(
            jobs, kind="company", subject_name="某公司", now=NOW, functions=["研发"] * 20)}
        self.assertIn("function_share", keys)


class TrendTest(unittest.TestCase):
    """趋势只能来自每日快照。没有快照就没有趋势——不许用 first_seen_at 分窗口凑。"""

    def test_no_snapshot_no_trend(self):
        self.assertEqual(S.compute_trends([], 100, NOW), [])

    def test_trend_from_snapshot(self):
        snaps = [{"day": (NOW.date() - timedelta(days=30)).isoformat(), "active_count": 100}]
        out = S.compute_trends(snaps, 130, NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["metric_key"], "hiring_trend_30d_pct")
        self.assertAlmostEqual(out[0]["metric_value"], 30.0)
        self.assertIn("+30.0%", out[0]["content"])

    def test_trend_tolerates_three_day_cron_gap(self):
        snaps = [{"day": (NOW.date() - timedelta(days=32)).isoformat(), "active_count": 50}]
        self.assertEqual(len(S.compute_trends(snaps, 60, NOW)), 1)
        snaps = [{"day": (NOW.date() - timedelta(days=36)).isoformat(), "active_count": 50}]
        self.assertEqual(S.compute_trends(snaps, 60, NOW), [])

    def test_small_baseline_produces_no_percentage(self):
        snaps = [{"day": (NOW.date() - timedelta(days=30)).isoformat(), "active_count": 3}]
        self.assertEqual(S.compute_trends(snaps, 100, NOW), [])


class OwnershipConsistencyTest(unittest.TestCase):
    """业务线归属必须与 bu_extract 逐字一致，否则卡面计数与展开列表对不上。"""

    def test_assignment_matches_extractor_rule(self):
        titles = ["【主站】后端工程师", "电商-前端工程师", "TikTok Shop-数据分析",
                  "普通岗位无业务线"]
        jobs = [job(title=t) for t in titles]
        keys = {"主站", "电商", "tiktok shop"}
        buckets = S.assign_jobs_to_subjects(jobs, keys)
        self.assertEqual(len(buckets["主站"]), 1)
        self.assertEqual(len(buckets["电商"]), 1)
        self.assertEqual(len(buckets["tiktok shop"]), 1)
        # 与抽取器同一套 normalize_bu：展示名反查得到同一个桶
        self.assertEqual(bu_extract.normalize_bu("TikTok Shop"), "tiktok shop")

    def test_unknown_subject_gets_no_jobs(self):
        buckets = S.assign_jobs_to_subjects([job(title="【主站】后端")], {"电商"})
        self.assertEqual(buckets["电商"], [])


if __name__ == "__main__":
    unittest.main()


class FetchSubjectsTest(unittest.TestCase):
    """I4c 回归：retired 主体必须跟 rejected 一样被派生层排除。

    旧实现把 status in ('active','retired') 都纳入派生：一个被 admin 治理下架（或被
    bu_extract 自动退役）的主体，只要当前在招岗数仍达标，plan_subject_rows 就会复用
    旧行 id、把它的 insight_items 原地写回 status='active'——治理动作被下一轮派生
    悄悄撤销。重新激活应由 bu_extract（业务线重新进入候选名单时）决定，不该由这条
    派生链越权。
    """

    def test_only_active_subjects_survive_the_filter(self):
        rows = [
            {"id": "s-active", "status": "active"},
            {"id": "s-retired", "status": "retired"},
            {"id": "s-rejected", "status": "rejected"},
        ]
        with mock.patch.object(S.db, "fetch_all_rows", return_value=rows):
            result = S.fetch_subjects(None)
        self.assertEqual([r["id"] for r in result], ["s-active"])


class WritePlanTest(unittest.TestCase):
    """写入计划：复用已有行的 id 走批量 upsert，不再一行一次 HTTP。"""

    SUBJECT = {"id": "sub-1", "name": "飞书", "kind": "business_unit"}

    def _metric(self, key="hiring_volume_30d"):
        return {
            "metric_key": key, "metric_value": 47, "metric_unit": "个",
            "dimension": "hiring", "title": "飞书", "content": "近 30 天新挂出 47 个（基于 397 个在招岗）。",
            "sample_size": 397, "scope": {}, "payload": {"sample_n": 397},
            "time_window": "截至 2026-09-03 的在招岗位",
        }

    def test_new_metric_gets_fresh_id(self):
        rows, retire = S.plan_subject_rows(self.SUBJECT, "c1", [self._metric()], [], "now", 14)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["id"])
        self.assertEqual(rows[0]["origin"], "derived")
        self.assertEqual(rows[0]["assertion"], "signal")
        self.assertEqual(retire, [])

    def test_existing_metric_reuses_id_so_upsert_updates_in_place(self):
        existing = [{"id": "row-1", "metric_key": "hiring_volume_30d", "status": "active"}]
        rows, _ = S.plan_subject_rows(self.SUBJECT, "c1", [self._metric()], existing, "now", 14)
        self.assertEqual(rows[0]["id"], "row-1")

    def test_vanished_metric_is_retired_not_deleted(self):
        existing = [{"id": "row-old", "metric_key": "salary_range_k", "status": "active"}]
        rows, retire = S.plan_subject_rows(self.SUBJECT, "c1", [self._metric()], existing, "now", 14)
        self.assertEqual(retire, ["row-old"])
        self.assertEqual(len(rows), 1)

    def test_derived_rows_expire_so_a_stalled_pipeline_stops_showing_numbers(self):
        rows, _ = S.plan_subject_rows(self.SUBJECT, "c1", [self._metric()], [], "now", 14)
        self.assertTrue(rows[0]["valid_until"])


class ZeroJobCompanyTest(unittest.TestCase):
    """公司一个在招岗都没有时，旧的派生条目也要退役——与在招岗 1~9 个时同一个处置。

    旧实现在 `if not jobs: continue` 处整家跳过，走不到 plan_subject_rows 的退役分支：
    源被停用 / 岗位整批下架 / 挂错名纠正之后，按那批岗算出来的条目还 active 到 valid_until。
    """

    COMPANY = {"id": "sub-co", "company_id": "c1", "kind": "company", "name": "某公司"}
    BU = {"id": "sub-bu", "company_id": "c1", "kind": "business_unit", "name": "飞书"}
    NAMES = {"c1": ["某公司"]}
    EXISTING = {
        "sub-co": [
            {"id": "co-a", "subject_id": "sub-co", "metric_key": "city_share", "status": "active"},
            {"id": "co-b", "subject_id": "sub-co", "metric_key": "bucket_share", "status": "active"},
            {"id": "co-old", "subject_id": "sub-co", "metric_key": "salary_range_k", "status": "retired"},
        ],
        "sub-bu": [
            {"id": "bu-a", "subject_id": "sub-bu", "metric_key": "bu_job_count", "status": "active"},
        ],
    }

    def _run_main(self, argv, *, jobs, subjects=None, names=None, existing=None, write_error=None):
        """真跑 main()，只把读写库的边界换掉。返回 (写库调用, 台账调用, 屏幕输出)。"""
        subjects = [self.COMPANY, self.BU] if subjects is None else subjects

        def fake_write(sb, rows, retire, now, batch=200):
            if write_error:
                raise write_error
            return len(rows), len(retire)

        out = io.StringIO()
        with contextlib.ExitStack() as stack:
            patch = lambda target, name, **kw: stack.enter_context(  # noqa: E731
                mock.patch.object(target, name, **kw))
            patch(sys, "argv", new=["bu_signals.py", *argv])
            patch(S.db, "get_supabase", return_value=mock.MagicMock())
            patch(S, "fetch_subjects", return_value=subjects)
            patch(S, "fetch_company_names", return_value=self.NAMES if names is None else names)
            patch(S, "fetch_existing_items",
                  return_value=self.EXISTING if existing is None else existing)
            patch(S, "fetch_snapshots", return_value={})
            patch(S.jobs_db, "get_conn", return_value=mock.MagicMock())
            patch(S, "fetch_jobs_for_company", side_effect=jobs)
            patch(S.job_function, "classify_titles", side_effect=lambda ts: [None] * len(list(ts)))
            write = patch(S, "write_rows", side_effect=fake_write)
            patch(S, "record_snapshots", side_effect=lambda sb, snaps, batch=200: len(snaps))
            record = patch(S.ops_runs, "record_ops_run")
            stack.enter_context(contextlib.redirect_stdout(out))
            S.main()
        return write, record, out.getvalue()

    @staticmethod
    def _retired(write):
        return sorted(rid for call in write.call_args_list for rid in call.args[2])

    @staticmethod
    def _upserted(write):
        return [row for call in write.call_args_list for row in call.args[1]]

    @staticmethod
    def _ledger(record):
        return record.call_args.args[2]

    def test_zero_jobs_retires_every_active_item_of_every_subject(self):
        write, record, _ = self._run_main([], jobs=lambda conn, names: [])
        # 公司主体 + 业务线主体的 active 条目都退役；本来就 retired 的那条不重复写。
        self.assertEqual(self._retired(write), ["bu-a", "co-a", "co-b"])
        self.assertEqual(self._upserted(write), [])
        ledger = self._ledger(record)
        self.assertEqual(ledger["items_retired"], 3)
        self.assertEqual(ledger["zero_job_items_retired"], 3)
        self.assertEqual(ledger["companies_zero_jobs"], 1)
        self.assertEqual(ledger["failed"], 0)

    def test_fetch_failure_is_not_treated_as_zero_jobs(self):
        def boom(conn, names):
            raise RuntimeError("statement timeout")

        write, record, _ = self._run_main([], jobs=boom)
        # 「没取到」不是「取到 0 个」：一条都不许退役，并且要记一次失败。
        self.assertEqual(self._retired(write), [])
        ledger = self._ledger(record)
        self.assertEqual(ledger["failed"], 1)
        self.assertEqual(ledger["items_retired"], 0)
        self.assertEqual(ledger["companies_zero_jobs"], 0)

    def test_zero_jobs_with_nothing_active_writes_nothing(self):
        existing = {"sub-co": [{"id": "co-old", "subject_id": "sub-co",
                                "metric_key": "city_share", "status": "retired"}]}
        write, record, _ = self._run_main([], jobs=lambda conn, names: [], existing=existing)
        self.assertEqual(self._retired(write), [])
        self.assertEqual(self._ledger(record)["companies_zero_jobs"], 1)

    def test_dry_run_reports_the_plan_and_writes_nothing(self):
        write, record, printed = self._run_main(["--dry-run"], jobs=lambda conn, names: [])
        write.assert_not_called()
        record.assert_not_called()
        self.assertIn("某公司", printed)
        self.assertIn("3 条", printed)

    def test_dry_run_says_zero_out_loud_when_nothing_would_be_retired(self):
        # 「没有要退役的」也要明说，不能靠「没打印」让人去猜。
        write, _, printed = self._run_main(["--dry-run"], jobs=lambda conn, names: [], existing={})
        write.assert_not_called()
        self.assertIn("1 家公司 0 个在招岗", printed)
        self.assertIn("共 0 条", printed)

    def test_failed_retirement_write_is_counted_and_still_reaches_the_ledger(self):
        write, record, printed = self._run_main(
            [], jobs=lambda conn, names: [], write_error=RuntimeError("503"))
        write.assert_called_once()
        ledger = self._ledger(record)
        self.assertEqual(ledger["failed"], 1)
        self.assertEqual(ledger["items_retired"], 0)
        self.assertEqual(ledger["zero_job_items_retired"], 0)
        self.assertIn("退役失败", printed)

    def test_company_with_jobs_next_to_a_zero_job_company_is_untouched(self):
        other = {"id": "sub-ok", "company_id": "c2", "kind": "company", "name": "另一家"}
        existing = {**self.EXISTING, "sub-ok": [
            {"id": "ok-a", "subject_id": "sub-ok", "metric_key": "hiring_volume_30d",
             "status": "active"}]}
        fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        by_name = {"某公司": [], "另一家": [job(first_seen_at=fresh) for _ in range(S.MIN_COMPANY)]}
        write, record, _ = self._run_main(
            [], jobs=lambda conn, names: by_name[names[0]],
            subjects=[self.COMPANY, self.BU, other],
            names={"c1": ["某公司"], "c2": ["另一家"]}, existing=existing)
        # 两个方向各看一次：0 岗那家全退役；有岗那家照常重算，它的旧条目原地更新、不被退役。
        self.assertEqual(self._retired(write), ["bu-a", "co-a", "co-b"])
        upserted = self._upserted(write)
        self.assertTrue(upserted)
        self.assertEqual({row["subject_id"] for row in upserted}, {"sub-ok"})
        self.assertIn("ok-a", {row["id"] for row in upserted})
        ledger = self._ledger(record)
        self.assertEqual(ledger["companies_scanned"], 2)
        self.assertEqual(ledger["companies_zero_jobs"], 1)

    def test_single_company_run_is_not_held_back_by_the_ratio(self):
        # 手动只跑一家（--company）而那一家正好 0 岗：这正是要退役的用法。
        write, _, _ = self._run_main(["--company", "某公司"], jobs=lambda conn, names: [])
        self.assertEqual(self._retired(write), ["bu-a", "co-a", "co-b"])

    def _fleet(self, *, dead, gone, healthy):
        """造一批公司：dead=0 岗且早就没有条目；gone=0 岗但还挂着条目；healthy=有岗有条目。"""
        subjects, names, existing, jobs_by_name = [], {}, {}, {}
        fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for kind, count in (("dead", dead), ("gone", gone), ("healthy", healthy)):
            for i in range(count):
                key = f"{kind}{i}"
                subjects.append({"id": f"s-{key}", "company_id": f"c-{key}",
                                 "kind": "company", "name": key})
                names[f"c-{key}"] = [key]
                if kind != "dead":
                    existing[f"s-{key}"] = [{"id": f"item-{key}", "subject_id": f"s-{key}",
                                             "metric_key": "hiring_volume_30d", "status": "active"}]
                jobs_by_name[key] = ([job(first_seen_at=fresh) for _ in range(S.MIN_COMPANY)]
                                     if kind == "healthy" else [])
        return dict(subjects=subjects, names=names, existing=existing,
                    jobs=lambda conn, names: jobs_by_name[names[0]])

    def test_most_item_holding_companies_reading_zero_blocks_the_retirement(self):
        # 挂着条目的 25 家里 20 家同时读出 0 岗：更像岗位库本身出了问题，不是它们真的都不招了。
        # 30 家早就没条目的 0 岗公司不进分母——算进去就成了 20/55，闸门形同虚设。
        write, record, printed = self._run_main([], **self._fleet(dead=30, gone=20, healthy=5))
        self.assertEqual(self._retired(write), [])
        # 有岗的那 5 家照常重算，不受牵连。
        self.assertEqual(len({row["subject_id"] for row in self._upserted(write)}), 5)
        ledger = self._ledger(record)
        self.assertEqual(ledger["zero_job_retire_blocked"], 20)
        self.assertEqual(ledger["items_retired"], 0)
        # 台账必须是 failed：看门狗只认 failed，记成 partial 等于没人知道闸门拦过。
        self.assertEqual(record.call_args.kwargs["status"], "failed")
        self.assertIn("::warning::", printed)

    def test_long_dead_profiles_do_not_trip_the_gate(self):
        # 0 岗公司的主体没人清，只增不减。拿「0 岗公司 / 全部公司」当比例会一路爬到 50% 误拦
        #（这里 32/52 = 62%）；真正异常的是「昨天还有条目、今天读出 0 岗」的占比（2/22）。
        write, record, _ = self._run_main([], **self._fleet(dead=30, gone=2, healthy=20))
        self.assertEqual(self._retired(write), ["item-gone0", "item-gone1"])
        ledger = self._ledger(record)
        self.assertEqual(ledger["zero_job_retire_blocked"], 0)
        self.assertEqual(ledger["companies_zero_jobs"], 32)
        self.assertEqual(record.call_args.kwargs["status"], "success")

    def test_blocked_dry_run_still_lists_what_would_have_been_retired(self):
        # 闸门拦下时，人要靠这份名单判断是不是误报。
        write, _, printed = self._run_main(
            ["--dry-run"], **self._fleet(dead=0, gone=20, healthy=5))
        write.assert_not_called()
        self.assertIn("gone0", printed)
        self.assertIn("::warning::", printed)

    def test_guard_thresholds(self):
        # 2026-10-10 真库：挂着派生条目的 1,129 家里 6 家读出 0 岗（0.5%）。
        self.assertTrue(S.zero_job_retire_allowed(6, 1129))
        self.assertFalse(S.zero_job_retire_allowed(1129, 1129))
        # 恰好一半放行，多一家就拦。
        self.assertTrue(S.zero_job_retire_allowed(10, 20))
        self.assertFalse(S.zero_job_retire_allowed(11, 20))
        # 不到 ZERO_JOB_GUARD_MIN_COMPANIES 家不看比例（手动跑一家 / 小批量）。
        self.assertTrue(S.zero_job_retire_allowed(1, 1))
        self.assertTrue(S.zero_job_retire_allowed(0, 0))
