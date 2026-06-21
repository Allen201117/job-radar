"""ops_runs 台账写入单测：写入失败必须被吞掉，不能影响原 workflow。"""
import unittest
from datetime import datetime, timezone

import ops_runs


class _FakeQuery:
    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail

    def insert(self, row):
        if self.fail:
            raise RuntimeError("ledger unavailable")
        self.store.append(row)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("ledger unavailable")
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    def table(self, name):
        self.table_name = name
        return _FakeQuery(self.rows, self.fail)


class OpsRunsTest(unittest.TestCase):
    def test_records_shanghai_run_date_and_metrics(self):
        sb = _FakeSB()
        ok = ops_runs.record_ops_run(
            sb,
            "liveness_sweep",
            {"checked": 12, "expired": 3},
            status="partial",
            started_at="2026-06-21T16:30:00+00:00",
            finished_at="2026-06-21T16:40:00+00:00",
        )
        self.assertTrue(ok)
        self.assertEqual(sb.table_name, "ops_runs")
        self.assertEqual(sb.rows[0]["run_date"], "2026-06-22")
        self.assertEqual(sb.rows[0]["metrics"], {"checked": 12, "expired": 3})
        self.assertEqual(sb.rows[0]["status"], "partial")

    def test_write_failure_is_swallowed(self):
        self.assertFalse(
            ops_runs.record_ops_run(
                _FakeSB(fail=True),
                "enrich_backlog",
                {"checked": 1},
                started_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
            )
        )

    def test_status_from_counts(self):
        self.assertEqual(ops_runs.status_from_counts(0, 0), "success")
        self.assertEqual(ops_runs.status_from_counts(10, 0), "success")
        self.assertEqual(ops_runs.status_from_counts(10, 2), "partial")
        self.assertEqual(ops_runs.status_from_counts(10, 10), "failed")


if __name__ == "__main__":
    unittest.main()
