"""enrich_row 结果分流 + 巡检队列冷却（2026-08-28 管线优化）。

钉死两条不变量：
1. 抓取抛异常（网络错/超时/限流）绝不能落进 'alive' 分支盖 enrich_checked_at——
   「没查到」≠「确认在招」，否则死岗被反复盖活章且插到轮转队列末尾（审阅 P0-7 根因）。
2. 巡检队列必须带冷却窗（20h 内刚探过的不再入队），否则小体量 adapter 每日被全量重探 3 次。
"""
import unittest
from unittest import mock

import enrich
import enrich_backlog


def _row(**kw):
    base = {"id": "job-1", "source_id": "src-1", "title": "t", "jd_url": "https://x/1",
            "job_type": None, "summary": None, "enrich_fail_count": 0}
    base.update(kw)
    return base


SRC = {"id": "src-1", "adapter_name": "hotjob", "company": "某司", "source_url": "https://x"}


class EnrichRowResultRouting(unittest.TestCase):
    def test_fetch_error_with_summary_returns_err_and_writes_nothing(self):
        """巡检路径：已有正文的岗抓取失败 → 'err'，不盖章不写库（留队列下轮重试）。"""
        with mock.patch.object(enrich, "enrich_one", side_effect=RuntimeError("timeout")), \
                mock.patch.object(enrich_backlog.jobs_db, "execute") as ex:
            res = enrich_backlog.enrich_row(None, _row(summary="旧正文"), SRC,
                                            dry_run=False, jobs_conn=object())
        self.assertEqual(res, "err")
        ex.assert_not_called()

    def test_fetch_error_without_summary_still_counts_dead_letter(self):
        """backlog 路径：空 summary 岗抓取失败 → 仍走 'miss'（fail_count+1 有界重试，防无限回队）。"""
        with mock.patch.object(enrich, "enrich_one", side_effect=RuntimeError("boom")), \
                mock.patch.object(enrich_backlog.jobs_db, "execute") as ex:
            res = enrich_backlog.enrich_row(None, _row(), SRC, dry_run=False, jobs_conn=object())
        self.assertEqual(res, "miss")
        sql = ex.call_args[0][1]
        self.assertIn("enrich_fail_count", sql)

    def test_closed_signal_still_expires(self):
        with mock.patch.object(enrich, "enrich_one", side_effect=enrich.JobClosedError("1017")), \
                mock.patch.object(enrich_backlog.jobs_db, "execute") as ex:
            res = enrich_backlog.enrich_row(None, _row(summary="旧正文"), SRC,
                                            dry_run=False, jobs_conn=object())
        self.assertEqual(res, "expired")
        self.assertIn("status", ex.call_args[0][1])

    def test_clean_empty_body_with_summary_is_alive_and_stamps(self):
        """请求成功但正文为空、已有 summary → 'alive' 只盖复检时间戳（原行为保持）。"""
        with mock.patch.object(enrich, "enrich_one", return_value=""), \
                mock.patch.object(enrich_backlog.jobs_db, "execute") as ex:
            res = enrich_backlog.enrich_row(None, _row(summary="旧正文"), SRC,
                                            dry_run=False, jobs_conn=object())
        self.assertEqual(res, "alive")
        sql = ex.call_args[0][1]
        self.assertIn("enrich_checked_at", sql)
        self.assertNotIn("status", sql)


class LivenessQueueCooldown(unittest.TestCase):
    def test_hk_sql_filters_recently_checked(self):
        captured = {}

        def fake_fetch_all(conn, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return []

        fake_sb = object()
        with mock.patch.object(enrich_backlog.db, "fetch_all_rows",
                               return_value=[{"id": "src-1", "company": "c",
                                             "source_url": "https://x", "adapter_name": "hotjob"}]), \
                mock.patch.object(enrich_backlog.jobs_db, "fetch_all", side_effect=fake_fetch_all):
            enrich_backlog.fetch_liveness_queue(fake_sb, ("hotjob",), jobs_conn=object())
        self.assertIn("enrich_checked_at is null", captured["sql"])
        self.assertIn("make_interval(hours => %s)", captured["sql"])
        self.assertIn(enrich_backlog.LIVENESS_COOLDOWN_HOURS, captured["params"])
        # 轮转排序语义不变：仍按 source_id 打头吃部分索引、NULL 最先。
        self.assertIn("order by source_id, enrich_checked_at asc nulls first", captured["sql"])


class AdaptiveTripCountsErrors(unittest.TestCase):
    def test_err_counts_toward_trip_ratio(self):
        """网络异常改走 err 后，限流特征（异常型 429/超时）必须仍能触发熔断。"""
        self.assertTrue(enrich_backlog.should_trip_adapter(50, 20 + 20))
        self.assertFalse(enrich_backlog.should_trip_adapter(50, 20 + 0))


if __name__ == "__main__":
    unittest.main()
