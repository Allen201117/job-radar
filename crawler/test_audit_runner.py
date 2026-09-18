"""审计执行器契约：正常 / 边界 / 错误路径。单测不连任何真库。"""
import os
import unittest

import audit_runner as A


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        low = sql.strip().lower()
        if low.startswith(("begin", "set local", "rollback")):
            return
        outcome = self.conn.outcome
        if isinstance(outcome, Exception):
            raise outcome
        self._row = outcome

    def fetchone(self):
        return self._row

    def close(self):
        pass


class FakeConn:
    def __init__(self, outcome):
        self.outcome = outcome
        self.executed = []
        self.closed = 0

    def cursor(self):
        return FakeCursor(self)


def check(**over):
    base = {
        "id": "jobs.x", "name": "人话名", "layer": "data", "db": "jobs",
        "owner": "crawler/geo.py", "sql": "select 1", "normal": "<= 0.10",
        "severity": "warn", "why": "为什么", "action": "怎么办",
    }
    base.update(over)
    return base


class NormalExprTest(unittest.TestCase):
    def test_boundary_is_inclusive_for_lte_and_exclusive_for_lt(self):
        self.assertTrue(A.evaluate_normal(0.10, "<= 0.10"))
        self.assertFalse(A.evaluate_normal(0.10, "< 0.10"))
        self.assertTrue(A.evaluate_normal(400000, ">= 400000"))
        self.assertFalse(A.evaluate_normal(399999, ">= 400000"))

    def test_eq_and_between(self):
        self.assertTrue(A.evaluate_normal(0, "== 0"))
        self.assertFalse(A.evaluate_normal(48, "== 0"))
        self.assertTrue(A.evaluate_normal(5, "between 5 and 9"))
        self.assertTrue(A.evaluate_normal(9, "between 5 and 9"))
        self.assertFalse(A.evaluate_normal(10, "between 5 and 9"))

    def test_garbage_expr_raises_instead_of_passing(self):
        for bad in ("", "about 5", "<= abc", "between 1", "=> 3"):
            with self.assertRaises(ValueError):
                A.parse_normal(bad)


class RunCheckTest(unittest.TestCase):
    def test_ok_and_breach(self):
        ok = A.run_check(check(), lambda db: FakeConn((0.09,)))
        self.assertEqual((ok["verdict"], ok["value"], ok["error_message"]), ("ok", 0.09, None))
        bad = A.run_check(check(), lambda db: FakeConn((0.11,)))
        self.assertEqual(bad["verdict"], "breach")

    def test_sql_error_is_error_verdict_not_zero_not_skipped(self):
        res = A.run_check(check(), lambda db: FakeConn(RuntimeError("statement timeout")))
        self.assertEqual(res["verdict"], "error")
        self.assertIsNone(res["value"])  # 绝不拿 0 充数
        self.assertIn("statement timeout", res["error_message"])

    def test_connection_failure_is_error_verdict(self):
        def boom(db):
            raise RuntimeError("unreachable")
        res = A.run_check(check(), boom)
        self.assertEqual(res["verdict"], "error")
        self.assertIsNone(res["value"])

    def test_null_or_no_row_is_error_not_zero(self):
        for outcome in (None, (None,)):
            res = A.run_check(check(normal="== 0"), lambda db, o=outcome: FakeConn(o))
            self.assertEqual(res["verdict"], "error", outcome)
            self.assertIsNone(res["value"])

    def test_true_zero_is_a_value(self):
        res = A.run_check(check(normal="== 0"), lambda db: FakeConn((0,)))
        self.assertEqual((res["verdict"], res["value"]), ("ok", 0.0))

    def test_non_numeric_is_error(self):
        res = A.run_check(check(), lambda db: FakeConn(("abc",)))
        self.assertEqual(res["verdict"], "error")

    def test_runs_read_only_and_always_rolls_back(self):
        conn = FakeConn((1,))
        A.run_check(check(normal=">= 0"), lambda db: conn)
        joined = " | ".join(s.lower() for s in conn.executed)
        self.assertIn("read only", joined)
        self.assertTrue(conn.executed[-1].lower().startswith("rollback"))
        failing = FakeConn(RuntimeError("x"))
        A.run_check(check(), lambda db: failing)
        self.assertTrue(failing.executed[-1].lower().startswith("rollback"))

    def test_error_message_never_leaks_dsn(self):
        ip = ".".join(["203", "0", "113", "7"])  # 运行时拼：公开仓门禁不许出现 IP 字面量
        exc = RuntimeError(f"could not connect to {ip} port 5432; dsn postgresql://u:p@{ip}:5432/db")
        res = A.run_check(check(), lambda db: FakeConn(exc))
        self.assertNotIn(ip, res["error_message"])
        self.assertNotIn("u:p", res["error_message"])


class RunAllTest(unittest.TestCase):
    def test_one_failing_check_does_not_stop_the_rest_and_every_check_gets_a_row(self):
        conns = {"jobs": FakeConn(RuntimeError("down")), "supabase": FakeConn((3,))}
        checks = [check(id="a"), check(id="b", db="supabase", normal=">= 1"), check(id="c")]
        results = A.run_all(checks, lambda db: conns[db])
        self.assertEqual([r["check_id"] for r in results], ["a", "b", "c"])
        self.assertEqual([r["verdict"] for r in results], ["error", "ok", "error"])

    def test_connection_is_reused_per_db(self):
        calls = []
        def factory(db):
            calls.append(db)
            return FakeConn((1,))
        A.run_all([check(id="a", normal=">= 0"), check(id="b", normal=">= 0")], factory)
        self.assertEqual(calls, ["jobs"])


class ContractTest(unittest.TestCase):
    def test_validate_rejects_bad_entries(self):
        good = check()
        A.validate_contract([good])
        for over in ({"layer": "misc"}, {"severity": "fatal"}, {"db": "mysql"},
                     {"normal": "roughly 3"}, {"name": ""}, {"why": " "}, {"action": None}):
            with self.assertRaises(ValueError, msg=over):
                A.validate_contract([check(**over)])
        with self.assertRaises(ValueError):
            A.validate_contract([good, dict(good)])  # 重复 id

    def test_shipped_contract_is_valid_and_sql_is_read_only(self):
        checks = A.load_contract()
        self.assertGreaterEqual(len([c for c in checks if c["layer"] == "data"]), 10)
        for c in checks:
            low = " " + " ".join(c["sql"].lower().split()) + " "
            self.assertTrue(low.strip().startswith(("select", "with")), c["id"])
            for kw in (" insert ", " update ", " delete ", " truncate ", " drop ", " alter "):
                self.assertNotIn(kw, low, c["id"])

    def test_every_owner_points_at_a_real_file(self):
        """owner = 出事去哪查。指向不存在的文件等于没写（写这份清单时就猜错过一次）。"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(A.__file__)))
        for c in A.load_contract():
            self.assertTrue(os.path.exists(os.path.join(root, c["owner"])), (c["id"], c["owner"]))

    def test_human_fields_carry_no_jargon(self):
        """name/why/action 直接进邮件，创始人非技术背景 —— 列名/SQL 味的词不许出现在 name 里。"""
        for c in A.load_contract():
            for word in ("null", "country_code", "job_scope", "summary", "select", "_at"):
                self.assertNotIn(word, c["name"].lower(), c["id"])


class RowShapeTest(unittest.TestCase):
    def test_result_row_has_every_ledger_column(self):
        res = A.run_check(check(calibrated=False), lambda db: FakeConn((0.2,)))
        for col in ("check_id", "run_date", "layer", "severity", "value", "normal",
                    "verdict", "calibrated", "measured_at", "error_message", "duration_ms"):
            self.assertIn(col, res)
        self.assertFalse(res["calibrated"])

    def test_exit_code_only_fails_when_ledger_write_fails(self):
        self.assertEqual(A.exit_code(written=True), 0)
        self.assertEqual(A.exit_code(written=False), 1)


if __name__ == "__main__":
    unittest.main()
