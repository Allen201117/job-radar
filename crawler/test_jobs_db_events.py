"""02 spec §5 / §6.5：岗位生命周期事件——触发规则 + 按天去重键 + expired 不复活 + 写失败不影响 upsert。
纯函数 plan_*（不连库）+ record_job_events best-effort（mock execute_values）。"""
import unittest
from contextlib import contextmanager
from unittest import mock

import jobs_db

DAY = "2026-06-25"


def keys(events):
    return [e[0] for e in events]


def types(events):
    return [e[1] for e in events]


class PlanUpsertEventsTest(unittest.TestCase):
    def test_insert_emits_first_seen(self):
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status=None, old_posted_at=None,
            new_status="active", new_posted_at=None, day=DAY)
        self.assertEqual(types(ev), ["FIRST_SEEN"])
        self.assertEqual(keys(ev), ["FIRST_SEEN:J"])  # 一辈子一条（无日期）

    def test_insert_with_official_posted(self):
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status=None, old_posted_at=None,
            new_status="active", new_posted_at="2026-06-01", day=DAY)
        self.assertEqual(types(ev), ["FIRST_SEEN", "OFFICIAL_POSTED"])
        self.assertEqual(keys(ev)[1], "OFFICIAL_POSTED:J")

    def test_update_gains_official_posted_once(self):
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status="active", old_posted_at=None,
            new_status="active", new_posted_at="2026-06-01", day=DAY)
        self.assertEqual(types(ev), ["OFFICIAL_POSTED"])

    def test_update_posted_already_known_no_event(self):
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status="active", old_posted_at="2026-05-01",
            new_status="active", new_posted_at="2026-05-01", day=DAY)
        self.assertEqual(ev, [])

    def test_removed_to_active_reappeared_day_keyed(self):
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status="removed", old_posted_at="2026-05-01",
            new_status="active", new_posted_at="2026-05-01", day=DAY)
        self.assertEqual(types(ev), ["REAPPEARED"])
        self.assertEqual(keys(ev), [f"REAPPEARED:J:{DAY}"])  # 按天去重

    def test_expired_never_reappears(self):
        # expired 黏住（有效新状态仍 expired）→ 绝不产生 REAPPEARED（保 expired sticky 不变量）
        ev = jobs_db.plan_upsert_events(
            job_id="J", source_id="S", old_status="expired", old_posted_at="2026-05-01",
            new_status="expired", new_posted_at="2026-05-01", day=DAY)
        self.assertEqual(ev, [])

    def test_close_and_confirm_keys_day_deduped(self):
        self.assertEqual(jobs_db.plan_close_event("J", "S", DAY)[0], f"CLOSED:J:{DAY}")
        self.assertEqual(jobs_db.plan_close_event("J", "S", DAY)[1], "CLOSED")
        self.assertEqual(jobs_db.plan_confirm_event("J", "S", DAY)[0], f"CONFIRMED_OPEN:J:{DAY}")


class RecordJobEventsTest(unittest.TestCase):
    def _fake_conn(self):
        @contextmanager
        def cursor():
            yield object()
        conn = mock.Mock()
        conn.cursor = cursor
        return conn

    def test_empty_returns_zero(self):
        self.assertEqual(jobs_db.record_job_events(self._fake_conn(), []), 0)

    def test_happy_path_inserts(self):
        ev = [("FIRST_SEEN:J", "FIRST_SEEN", "J", "S", {})]
        with mock.patch.object(jobs_db.psycopg2.extras, "execute_values") as m:
            n = jobs_db.record_job_events(self._fake_conn(), ev)
        self.assertEqual(n, 1)
        self.assertTrue(m.called)
        # SQL 必须带幂等去重
        sql = m.call_args[0][1]
        self.assertIn("on conflict (event_key) do nothing", sql.lower())

    def test_write_failure_does_not_raise(self):
        ev = [("FIRST_SEEN:J", "FIRST_SEEN", "J", "S", {})]
        with mock.patch.object(jobs_db.psycopg2.extras, "execute_values", side_effect=RuntimeError("boom")):
            n = jobs_db.record_job_events(self._fake_conn(), ev)  # 不许抛
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
