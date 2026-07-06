"""01 spec §3.1 / §7.3：新岗优先核验——audit_dead_links --prioritize-new 只取近 48h 新增、从未核验的 SPA 岗，
按 first_seen_at desc 排队头（消灭 7 天盲区）。不连真库：mock jobs_db.fetch_all 捕获 SQL 断言。"""
import unittest
from unittest import mock

import audit_dead_links
import jobs_db


class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def execute(self):
        return _FakeResp(self._data)


class _FakeSupabase:
    """只需支持 sources 表查 browser adapter 的 id 列表。"""

    def table(self, name):
        assert name == "sources"
        return _FakeQuery([{"id": "src-1"}, {"id": "src-2"}])


class PrioritizeNewTest(unittest.TestCase):
    def _capture_sql(self, prioritize_new):
        captured = {}

        def fake_fetch_all(conn, sql, params):
            captured["sql"] = " ".join(sql.lower().split())
            captured["params"] = params
            return [{"id": "j1", "title": "T", "company": "C", "jd_url": "u"}]

        with mock.patch.object(jobs_db, "fetch_all", side_effect=fake_fetch_all):
            audit_dead_links.fetch_browser_liveness(
                _FakeSupabase(), limit=300, shard="0/1", jobs_conn=object(), prioritize_new=prioritize_new
            )
        return captured["sql"]

    def test_prioritize_new_filters_recent_unchecked(self):
        sql = self._capture_sql(prioritize_new=True)
        self.assertIn("enrich_checked_at is null", sql)
        self.assertIn("first_seen_at >= now() - interval '48 hours'", sql)
        self.assertIn("order by first_seen_at desc", sql)

    def test_default_rotation_uses_oldest_first(self):
        sql = self._capture_sql(prioritize_new=False)
        # 默认轮转：按 enrich_checked_at NULLS FIRST、source_id 打头吃部分索引
        self.assertIn("order by source_id, enrich_checked_at asc nulls first", sql)
        self.assertNotIn("first_seen_at >= now()", sql)


class MustApplyCandidatePlanTest(unittest.TestCase):
    def test_must_apply_first_caps_headliner_quota_at_half_limit(self):
        must_rows = [{"id": str(i)} for i in range(1, 6)]
        regular_rows = [{"id": str(i)} for i in range(6, 10)]

        rows = audit_dead_links.merge_must_apply_candidates(must_rows, regular_rows, limit=5)

        # limit=5 时 50% 上限取 floor=2，不能让必投段吃掉超过半个分片。
        self.assertEqual([r["id"] for r in rows], ["1", "2", "6", "7", "8"])

    def test_regular_segment_excludes_already_picked_ids(self):
        must_rows = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        regular_rows = [{"id": "m2"}, {"id": "r1"}, {"id": "r2"}, {"id": "r3"}]

        rows = audit_dead_links.merge_must_apply_candidates(must_rows, regular_rows, limit=4)

        self.assertEqual([r["id"] for r in rows], ["m1", "m2", "r1", "r2"])

    def test_must_apply_only_uses_full_limit_without_regular_rows(self):
        must_rows = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        regular_rows = [{"id": "r1"}, {"id": "r2"}]

        rows = audit_dead_links.merge_must_apply_candidates(
            must_rows,
            regular_rows,
            limit=2,
            must_apply_only=True,
        )

        self.assertEqual([r["id"] for r in rows], ["m1", "m2"])


if __name__ == "__main__":
    unittest.main()
