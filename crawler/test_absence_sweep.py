"""list-absence 探活单测（纯函数 + mock conn，不打真库）。

红线：list-absence 会**下架岗位**——绝不能因 httpx 偶发空/半量把整源活岗误杀。
覆盖：① plan_absence_sweep 占比安全闸 + dry-run 门 ② sweep_absent_jobs apply/dry-run/skip 三态。
"""
import unittest
from unittest import mock

import jobs_db


class PlanAbsenceSweepTest(unittest.TestCase):
    def test_no_absent_is_noop(self):
        self.assertEqual(jobs_db.plan_absence_sweep(100, 0, apply=True)[0], "noop")

    def test_apply_when_fraction_safe(self):
        self.assertEqual(jobs_db.plan_absence_sweep(100, 40, apply=True)[0], "apply")

    def test_dry_run_when_not_applying(self):
        self.assertEqual(jobs_db.plan_absence_sweep(100, 40, apply=False)[0], "dry_run")

    def test_skip_when_fraction_too_high(self):
        action, reason = jobs_db.plan_absence_sweep(100, 60, apply=True)
        self.assertEqual(action, "skip")
        self.assertIn("60/100", reason)

    def test_fraction_boundary(self):
        # 50/100 == 0.5 不超阈 → apply；51/100 超 → skip
        self.assertEqual(jobs_db.plan_absence_sweep(100, 50, apply=True)[0], "apply")
        self.assertEqual(jobs_db.plan_absence_sweep(100, 51, apply=True)[0], "skip")

    def test_tiny_source_below_floor_not_gated(self):
        # active < min_active_floor(8) → 占比闸不挡（小源整体收缩可信），4/5 仍 apply
        self.assertEqual(jobs_db.plan_absence_sweep(5, 4, apply=True)[0], "apply")

    def test_at_floor_fraction_gate_applies(self):
        # active==8 ≥ floor → 5/8 超 0.5 → skip
        self.assertEqual(jobs_db.plan_absence_sweep(8, 5, apply=True)[0], "skip")


class _FakeCursor:
    def __init__(self, active, cand_ids, store):
        self.active = active
        self.cand_ids = cand_ids
        self.store = store
        self._last = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = sql.lower()
        if "count(*)" in s:
            self._last = [(self.active,)]
        elif "select id from jobs" in s:
            self._last = [(x,) for x in self.cand_ids]
        elif "update jobs set status = 'expired'" in s:
            ids = list(params[1])
            self.store["updated"] = ids
            self.rowcount = len(ids)
        else:
            self._last = []

    def fetchone(self):
        return self._last[0]

    def fetchall(self):
        return self._last


class _FakeConn:
    def __init__(self, active, cand_ids, store):
        self.active = active
        self.cand_ids = cand_ids
        self.store = store

    def cursor(self):
        return _FakeCursor(self.active, self.cand_ids, self.store)


class SweepAbsentJobsTest(unittest.TestCase):
    def test_apply_expires_absent(self):
        store = {}
        conn = _FakeConn(100, ["u1", "u2", "u3"], store)
        with mock.patch.object(jobs_db, "record_job_events", return_value=0):
            res = jobs_db.sweep_absent_jobs(conn, "src-1", "2026-06-28T00:00:00Z", apply=True)
        self.assertEqual(res["action"], "apply")
        self.assertEqual(res["expired"], 3)
        self.assertEqual(store["updated"], ["u1", "u2", "u3"])

    def test_dry_run_does_not_mutate(self):
        store = {}
        conn = _FakeConn(100, ["u1", "u2", "u3"], store)
        res = jobs_db.sweep_absent_jobs(conn, "src-1", "2026-06-28T00:00:00Z", apply=False)
        self.assertEqual(res["action"], "dry_run")
        self.assertEqual(res["expired"], 0)
        self.assertNotIn("updated", store)

    def test_skip_when_too_many_absent(self):
        store = {}
        conn = _FakeConn(100, [f"u{i}" for i in range(60)], store)
        res = jobs_db.sweep_absent_jobs(conn, "src-1", "2026-06-28T00:00:00Z", apply=True)
        self.assertEqual(res["action"], "skip")
        self.assertEqual(res["expired"], 0)
        self.assertNotIn("updated", store)


if __name__ == "__main__":
    unittest.main()
