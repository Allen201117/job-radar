import unittest
from datetime import datetime, timedelta, timezone

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
