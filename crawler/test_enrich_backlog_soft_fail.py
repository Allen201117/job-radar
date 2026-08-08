"""分片「够不着香港库」时的软失败语义。

背景：2026-08-08 实测同一轮 enrich-backlog 的 12 个分片里 11 个连库正常、只有 1 片全程被 RST
（GitHub 每片一台 runner、出口 IP 各不相同，个别 IP 被路径上掐掉）。重试再久也没用，
而队列是幂等的、下一轮会补上 —— 所以这一片该记台账、不该把整轮 CI 拖红。
但**只有「够不着库」能软化**：别的异常必须照常炸穿，否则就是吞错。
"""
import sys
import unittest
from unittest import mock

import enrich_backlog
import jobs_db


class SoftFailOnUnreachableTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ", {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "svc",
        })
        env.start()
        self.addCleanup(env.stop)

        argv = mock.patch.object(sys, "argv", ["enrich_backlog.py", "--adapter", "hotjob"])
        argv.start()
        self.addCleanup(argv.stop)

        sb = mock.patch.object(enrich_backlog.db, "get_supabase", return_value=mock.Mock())
        sb.start()
        self.addCleanup(sb.stop)

        rec = mock.patch.object(enrich_backlog.ops_runs, "record_ops_run")
        self.record = rec.start()
        self.addCleanup(rec.stop)

    def test_unreachable_shard_records_ledger_and_exits_clean(self):
        boom = jobs_db.JobsDbUnreachable("connection to server at \"<jobs-db>\" failed")
        with mock.patch.object(enrich_backlog, "drain", side_effect=boom):
            enrich_backlog.main()   # 不抛、不 SystemExit → CI 退 0

        self.record.assert_called_once()
        _sb, module, metrics = self.record.call_args.args
        self.assertEqual(module, "enrich_backlog")
        self.assertEqual(metrics["unreachable"], 1)
        self.assertEqual(metrics["adapter"], "hotjob")
        self.assertEqual(metrics["checked"], 0)
        # 台账必须照实记红：CI 不吵 ≠ 假装成功
        self.assertEqual(self.record.call_args.kwargs["status"], "failed")

    def test_other_errors_still_blow_up(self):
        """别的异常一律不许软化 —— 软失败只针对「够不着库」这一种。"""
        with mock.patch.object(enrich_backlog, "drain", side_effect=ValueError("真 bug")):
            with self.assertRaises(ValueError):
                enrich_backlog.main()
        self.record.assert_not_called()

    def test_plain_operational_error_is_not_softened(self):
        """库连上了、SQL 出错（普通 OperationalError）是真问题，必须炸。"""
        import psycopg2
        with mock.patch.object(enrich_backlog, "drain",
                               side_effect=psycopg2.OperationalError("deadlock detected")):
            with self.assertRaises(psycopg2.OperationalError):
                enrich_backlog.main()
        self.record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
