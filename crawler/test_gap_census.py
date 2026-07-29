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


class QueuePlanningTest(unittest.TestCase):
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
