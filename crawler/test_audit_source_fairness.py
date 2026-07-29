"""死活巡检轮转必须**按源摊名额**，不能让 UUID 靠后的源被饿死。

2026-07-28 实测：旧实现 `order by source_id, enrich_checked_at asc nulls first limit N`
等价于「按 source_id 的 UUID 大小从头审到 limit 用完为止」。华为的 source_id 前面压着
157154 个 active 岗，而一轮只取 ~9100 行 → 华为 460 个在招岗里 440 个**从未被探活过**、
最近一次探活停在 2026-07-09。718 个浏览器源里 UUID 靠后的都被同样饿死。
不连真库：mock jobs_db.fetch_all 捕获 SQL/参数断言。
"""
import unittest
from unittest import mock

import audit_dead_links
import jobs_db


class PerSourceQuotaTest(unittest.TestCase):
    def test_splits_budget_across_sources(self):
        self.assertEqual(audit_dead_links.per_source_quota(9100, 718), 13)
        self.assertEqual(audit_dead_links.per_source_quota(100, 10), 10)

    def test_always_at_least_one(self):
        """源比名额还多时每源也要分到 1，否则又变成「一部分源永远轮不到」。"""
        self.assertEqual(audit_dead_links.per_source_quota(5, 1000), 1)

    def test_handles_zero_sources_without_crashing(self):
        self.assertEqual(audit_dead_links.per_source_quota(100, 0), 100)


class RotationFairnessTest(unittest.TestCase):
    SRC = [f"{i:08d}-0000-0000-0000-000000000000" for i in range(400)]

    def _capture(self, **kwargs):
        seen = {}

        def fake_fetch_all(conn, sql, params=None):
            seen["sql"] = " ".join(sql.split())
            seen["params"] = params
            return []

        with mock.patch.object(jobs_db, "fetch_all", fake_fetch_all):
            audit_dead_links._fetch_browser_rows_pg(object(), self.SRC, 9100, **kwargs)
        return seen

    def test_rotation_query_is_per_source_lateral(self):
        seen = self._capture()
        self.assertIn("cross join lateral", seen["sql"].lower())
        self.assertNotIn("order by source_id,", seen["sql"].lower(),
                         "又退回全局按 source_id 排序 = UUID 靠后的源继续被饿死")
        # 每源名额与总上限都要传进去
        self.assertIn(audit_dead_links.per_source_quota(9100, len(self.SRC)), seen["params"])
        self.assertIn(9100, seen["params"])

    def test_inner_scan_still_keyed_on_source_id_for_the_index(self):
        """内层必须 source_id= 打头，才吃得到
        jobs_active_liveness_by_source_idx (source_id, enrich_checked_at nulls first) WHERE active。"""
        sql = self._capture()["sql"].lower()
        self.assertIn("source_id = s.source_id", sql)
        self.assertIn("status='active'", sql.replace(" = ", "="))
        self.assertIn("order by enrich_checked_at asc nulls first", sql)

    def test_prioritize_new_still_global_by_first_seen(self):
        """近 48h 新岗本就是小集合，仍走全局 first_seen_at desc，不摊名额。"""
        sql = self._capture(prioritize_new=True)["sql"].lower()
        self.assertIn("order by first_seen_at desc", sql)
        self.assertNotIn("cross join lateral", sql)
        self.assertIn("enrich_checked_at is null", sql)

    def test_must_apply_filter_applies_inside_the_per_source_scan(self):
        seen = self._capture(must_patterns=["%华为%"])
        self.assertIn("ilike any", seen["sql"].lower())
        self.assertIn("cross join lateral", seen["sql"].lower())
        self.assertIn(["%华为%"], list(seen["params"]))


if __name__ == "__main__":
    unittest.main()
