"""main() 中途崩溃必须留痕：补写 ops_runs(status=failed, crash=<异常类名>) 再原样抛出。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import campus_board_verify as M


class MainCrashRecordsFailedLedgerTest(unittest.TestCase):
    def test_crash_after_supabase_obtained_writes_failed_and_reraises(self):
        with patch.object(M.db, "get_supabase", return_value="fake-supabase-client"), \
             patch.object(M, "_run", side_effect=RuntimeError("boom")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["prog.py"]):
            with self.assertRaises(RuntimeError):
                M.main()
            self.assertEqual(rec.call_count, 1)
            args, kwargs = rec.call_args
            self.assertEqual(args[0], "fake-supabase-client")
            self.assertEqual(args[1], "campus_board_verify")
            # errors=1：规则 A 对本模块不再单凭 status 判零产出，崩溃必须显式计数。
            self.assertEqual(args[2], {"crash": "RuntimeError", "errors": 1})
            self.assertEqual(args[3], "failed")

    def test_supabase_itself_failing_reraises_without_calling_record_ops_run(self):
        with patch.object(M.db, "get_supabase", side_effect=ConnectionError("no db")), \
             patch.object(M.ops_runs, "record_ops_run") as rec, \
             patch("sys.argv", ["prog.py"]):
            with self.assertRaises(ConnectionError):
                M.main()
            rec.assert_not_called()


class _Resp:
    def __init__(self, data):
        self.data = data


class _AttemptsQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        return _Resp(self.rows)


class _Sb:
    def __init__(self, awaiting):
        self.awaiting = awaiting

    def table(self, _name):
        return _AttemptsQuery(self.awaiting)


class LedgerMetricsTest(unittest.TestCase):
    """台账口径（2026-09-23）：通过验收的状态叫 healthy，旧代码去数 "enabled" 恒为 0。"""

    def _run_with(self, states):
        cands = [{"id": "s%d" % i, "company": "C%d" % i, "adapter_name": "moka",
                  "source_url": "https://app.mokahr.com/campus-recruitment/c%d/1" % i,
                  "enabled": False} for i in range(len(states))]
        awaiting = [{"company": c["company"], "adapter_name": "moka"} for c in cands]

        class _Conn:
            def close(self):
                pass

        with patch.object(M.jobs_db, "enabled", return_value=True), \
             patch.object(M.db, "fetch_all_rows", return_value=cands), \
             patch.object(M.jobs_db, "get_conn", return_value=_Conn()), \
             patch.object(M, "verify_one", side_effect=list(states)), \
             patch.object(M, "upsert_attempt"), \
             patch.object(M.ops_runs, "record_ops_run") as rec:
            args = type("A", (), {"limit": 12})()
            self.assertEqual(M._run(_Sb(awaiting), args, None), 0)
        (_sb, module, metrics, status), _kw = rec.call_args
        self.assertEqual(module, "campus_board_verify")
        return metrics, status

    def test_healthy_candidate_is_counted_as_enabled(self):
        metrics, status = self._run_with(["healthy"] + ["empty_board"] * 11)
        self.assertEqual(metrics["enabled"], 1)
        self.assertEqual(metrics["pending"], 12)
        self.assertEqual(metrics["actionable"], 1)
        self.assertEqual(status, "partial")

    def test_all_empty_boards_have_no_actionable_work(self):
        # 板块空着等开闸 = 没有能产出的活；规则 A 据 actionable=0 判空队列，不报零产出。
        metrics, status = self._run_with(["empty_board"] * 12)
        self.assertEqual((metrics["enabled"], metrics["actionable"]), (0, 0))
        self.assertEqual(status, "failed")

    def test_crawl_failures_and_duplicates_are_actionable(self):
        metrics, _status = self._run_with(["unreachable", "duplicate_board", "empty_board"])
        self.assertEqual((metrics["enabled"], metrics["actionable"]), (0, 2))


if __name__ == "__main__":
    unittest.main()
