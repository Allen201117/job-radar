"""审计执行器契约：正常 / 边界 / 错误路径。单测不连任何真库。"""
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest import mock

import audit_runner as A

_FAKE_PING_URL = "https://hc-ping.example/test-uuid"


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
        for c in A.sql_checks(checks):
            for field in ("sql", "detail_sql"):
                if field not in c:
                    continue
                low = " " + " ".join(c[field].lower().split()) + " "
                self.assertTrue(low.strip().startswith(("select", "with")), (c["id"], field))
                for kw in (" insert ", " update ", " delete ", " truncate ", " drop ", " alter "):
                    self.assertNotIn(kw, low, (c["id"], field))

    def test_watchdog_source_checks_have_no_sql_and_are_excluded_from_sql_checks(self):
        """source=watchdog 的检查项不该有 sql/db（那是 ops_watchdog.py 自己测量的），
        且 audit_runner.sql_checks 必须把它们过滤掉，否则 main() 会拿它们去执行 SQL 而崩。"""
        checks = A.load_contract()
        watchdog_checks = [c for c in checks if c.get("source") == "watchdog"]
        self.assertGreater(len(watchdog_checks), 0, "shipped contract 应该已经桥接了 watchdog 规则")
        for c in watchdog_checks:
            self.assertNotIn(c, A.sql_checks(checks))
            self.assertIsInstance(c.get("rule"), str)
            self.assertTrue(c["rule"].strip())

    def test_validate_contract_accepts_watchdog_source_without_sql_or_db(self):
        watchdog_check = {
            "id": "watchdog.rule_z", "name": "人话名", "layer": "pipeline",
            "owner": "crawler/ops_watchdog.py", "rule": "Z", "normal": "== 0",
            "severity": "warn", "why": "为什么", "action": "怎么办", "source": "watchdog",
        }
        A.validate_contract([watchdog_check])  # 不该抛错——没有 sql/db 也合法

    def test_validate_contract_rejects_watchdog_source_missing_rule(self):
        watchdog_check = {
            "id": "watchdog.rule_z", "name": "人话名", "layer": "pipeline",
            "owner": "crawler/ops_watchdog.py", "normal": "== 0",
            "severity": "warn", "why": "为什么", "action": "怎么办", "source": "watchdog",
        }
        with self.assertRaises(ValueError):
            A.validate_contract([watchdog_check])

    def test_validate_contract_rejects_unknown_source(self):
        with self.assertRaises(ValueError):
            A.validate_contract([check(source="csv")])

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


class FakeOpener:
    """记录调用、不打真网络。outcome 控制第几次调用抛错（0-indexed），None 表示全部成功。"""

    def __init__(self, fail_until_call=None, exc=RuntimeError("boom")):
        self.calls = []
        self.fail_until_call = fail_until_call
        self.exc = exc

    def __call__(self, request, timeout):
        self.calls.append((request.full_url, request.data, timeout))
        if self.fail_until_call is not None and len(self.calls) <= self.fail_until_call:
            raise self.exc
        return None


class PingHeartbeatTest(unittest.TestCase):
    def test_url_suffix_per_outcome(self):
        opener = FakeOpener()
        A.ping_heartbeat("start", url=_FAKE_PING_URL, opener=opener)
        A.ping_heartbeat("success", url=_FAKE_PING_URL, opener=opener)
        A.ping_heartbeat("fail", url=_FAKE_PING_URL, opener=opener)
        urls = [c[0] for c in opener.calls]
        self.assertEqual(urls, [
            _FAKE_PING_URL + "/start",
            _FAKE_PING_URL,
            _FAKE_PING_URL + "/fail",
        ])

    def test_missing_url_is_skipped_and_says_so(self):
        buf = io.StringIO()
        opener = FakeOpener()
        with redirect_stdout(buf):
            result = A.ping_heartbeat("start", url=None, opener=opener)
        self.assertEqual(result, "skipped")
        self.assertEqual(opener.calls, [])
        self.assertIn("HEALTHCHECKS_PING_URL", buf.getvalue())
        self.assertIn("跳过", buf.getvalue())

    def test_missing_url_falls_back_to_env(self):
        opener = FakeOpener()
        with mock.patch.dict(os.environ, {"HEALTHCHECKS_PING_URL": _FAKE_PING_URL}):
            result = A.ping_heartbeat("start", opener=opener)
        self.assertEqual(result, "sent")
        self.assertEqual(len(opener.calls), 1)

    def test_request_failure_returns_failed_without_raising_and_without_leaking_url(self):
        opener = FakeOpener(fail_until_call=99)  # 每次都失败
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = A.ping_heartbeat("fail", url=_FAKE_PING_URL, opener=opener)
        self.assertEqual(result, "failed")
        out = buf.getvalue()
        self.assertNotIn(_FAKE_PING_URL, out)
        self.assertIn("RuntimeError", out)
        self.assertGreaterEqual(len(opener.calls), 2)  # 确实重试过

    def test_dry_run_sends_zero_pings(self):
        opener = FakeOpener()
        with mock.patch.dict(os.environ, {"HEALTHCHECKS_PING_URL": _FAKE_PING_URL}):
            buf = io.StringIO()
            with redirect_stdout(buf):
                with mock.patch.object(A, "_default_opener", opener):
                    code = A.main(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(opener.calls, [])
        self.assertIn("dry-run", buf.getvalue())

    def test_fail_body_is_redacted_and_capped(self):
        long_body = "postgresql://u:p@203.0.113.7:5432/db " + "x" * 400
        opener = FakeOpener()
        A.ping_heartbeat("fail", url=_FAKE_PING_URL, opener=opener, body=long_body)
        sent_body = opener.calls[0][1].decode("utf-8")
        self.assertNotIn("203.0.113.7", sent_body)
        self.assertLessEqual(len(sent_body), A._HEARTBEAT_BODY_MAX)


def _stub_checks_and_run(monkeypatch_target, verdicts):
    """main() 里跑到 write_results 前的那一段替身：假合约 + 假 run_all 结果。"""
    checks = [check(id=f"c{i}") for i in range(len(verdicts))]
    results = []
    for c, v in zip(checks, verdicts):
        row = A.run_check(c, lambda db: FakeConn((0.0,)))
        row["verdict"] = v
        results.append(row)
    return checks, results


class MainHeartbeatWiringTest(unittest.TestCase):
    def setUp(self):
        self.checks, self.results = _stub_checks_and_run(None, ["ok"])
        patcher1 = mock.patch.object(A, "load_contract", return_value=self.checks)
        patcher2 = mock.patch.object(A, "run_all", return_value=self.results)
        patcher1.start()
        patcher2.start()
        self.addCleanup(patcher1.stop)
        self.addCleanup(patcher2.stop)
        env_patcher = mock.patch.dict(os.environ, {"HEALTHCHECKS_PING_URL": _FAKE_PING_URL}, clear=False)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def _run_main(self, argv=None):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = A.main(argv or [])
        return code, buf.getvalue()

    def test_success_path_pings_start_then_success_in_order(self):
        calls = []

        def fake_ping(outcome, **kw):
            calls.append(outcome)
            return "sent"

        with mock.patch.object(A, "write_results", return_value=1), \
             mock.patch.object(A, "connect", return_value=object()), \
             mock.patch.object(A, "ping_heartbeat", side_effect=fake_ping):
            code, _ = self._run_main()
        self.assertEqual(code, 0)
        self.assertEqual(calls, ["start", "success"])

    def test_ledger_write_failure_pings_fail_and_exits_nonzero(self):
        calls = []

        def fake_ping(outcome, **kw):
            calls.append(outcome)
            return "sent"

        def boom_connect(db):
            raise RuntimeError("ledger down")

        with mock.patch.object(A, "connect", side_effect=boom_connect), \
             mock.patch.object(A, "ping_heartbeat", side_effect=fake_ping):
            code, out = self._run_main()
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["start", "fail"])
        self.assertIn("写入失败", out)

    def test_force_fail_env_skips_ledger_write_and_pings_fail(self):
        calls = []

        def fake_ping(outcome, **kw):
            calls.append(outcome)
            return "sent"

        write_called = []

        def fake_write(conn, results):
            write_called.append(True)
            return len(results)

        with mock.patch.dict(os.environ, {"AUDIT_FORCE_FAIL": "1"}), \
             mock.patch.object(A, "write_results", side_effect=fake_write), \
             mock.patch.object(A, "connect", return_value=object()), \
             mock.patch.object(A, "ping_heartbeat", side_effect=fake_ping):
            code, out = self._run_main()
        self.assertEqual(code, 1)
        self.assertEqual(calls, ["start", "fail"])
        self.assertEqual(write_called, [])
        self.assertIn("故障演练", out)

    def test_uncaught_exception_still_pings_fail_and_reraises(self):
        calls = []

        def fake_ping(outcome, **kw):
            calls.append(outcome)
            return "sent"

        with mock.patch.object(A, "run_all", side_effect=RuntimeError("kaboom")), \
             mock.patch.object(A, "ping_heartbeat", side_effect=fake_ping):
            with self.assertRaises(RuntimeError):
                self._run_main()
        self.assertEqual(calls, ["start", "fail"])


class DetailFakeCursor:
    """按 SQL 文本分流：数值查询与明细查询各给各的结果，便于单独让其中一条失败。"""

    def __init__(self, conn):
        self.conn = conn
        self._row = None
        self._rows = []
        self.description = None

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        low = sql.strip().lower()
        if low.startswith(("begin", "set local", "rollback")):
            return
        outcome = self.conn.detail if sql == self.conn.detail_sql else self.conn.scalar
        if isinstance(outcome, Exception):
            raise outcome
        if sql == self.conn.detail_sql:
            cols, self._rows = outcome
            self.description = [(c,) for c in cols]
        else:
            self._row = outcome

    def fetchone(self):
        return self._row

    def fetchmany(self, size):
        self.conn.fetchmany_sizes.append(size)
        return self._rows[:size]

    def close(self):
        pass


class DetailFakeConn:
    def __init__(self, scalar, detail, detail_sql="select title, key from pairs"):
        self.scalar = scalar
        self.detail = detail
        self.detail_sql = detail_sql
        self.executed = []
        self.fetchmany_sizes = []
        self.closed = 0

    def cursor(self):
        return DetailFakeCursor(self)


class DetailSqlTest(unittest.TestCase):
    """detail_sql：数值之外的「具体是哪几处」。它是附件——取不到不许拖累数值与判定，也不许静默。"""

    DETAIL_SQL = "select title, key from pairs"

    def _check(self, **over):
        return check(normal="<= 1", detail_sql=self.DETAIL_SQL, **over)

    def test_findings_land_in_detail_with_bridge_shape(self):
        conn = DetailFakeConn((2,), (["title", "key"], [("东方财富：1 个岗位…", "a | b"), ("宝洁：1 个岗位…", "c | d")]))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual((res["value"], res["verdict"]), (2.0, "breach"))
        self.assertEqual(res["detail"], {"findings": [
            {"title": "东方财富：1 个岗位…", "key": "a | b"}, {"title": "宝洁：1 个岗位…", "key": "c | d"}]})
        self.assertIsNone(res["error_message"])

    def test_detail_runs_read_only_and_rolls_back(self):
        conn = DetailFakeConn((0,), (["title", "key"], []))
        A.run_check(self._check(), lambda db: conn)
        i = conn.executed.index(self.DETAIL_SQL)
        self.assertIn("read only", conn.executed[i - 2].lower())
        self.assertTrue(conn.executed[i + 1].lower().startswith("rollback"))

    def test_columns_are_read_by_name_not_position(self):
        conn = DetailFakeConn((1,), (["key", "extra", "title"], [("a | b", "x", "人话")]))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual(res["detail"], {"findings": [{"title": "人话", "key": "a | b"}]})

    def test_capped_at_bridge_limit_and_title_truncated(self):
        rows = [("长" * 500, f"k{i}") for i in range(A.DETAIL_MAX_FINDINGS + 5)]
        conn = DetailFakeConn((40,), (["title", "key"], rows))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual(conn.fetchmany_sizes, [A.DETAIL_MAX_FINDINGS])
        self.assertEqual(len(res["detail"]["findings"]), A.DETAIL_MAX_FINDINGS)
        self.assertEqual(len(res["detail"]["findings"][0]["title"]), A.DETAIL_TITLE_MAX)

    def test_no_rows_means_no_detail(self):
        conn = DetailFakeConn((0,), (["title", "key"], []))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual(res["verdict"], "ok")
        self.assertIsNone(res["detail"])

    def test_detail_failure_keeps_value_and_verdict_and_says_why(self):
        ip = ".".join(["203", "0", "113", "7"])  # 运行时拼：公开仓门禁不许出现 IP 字面量
        conn = DetailFakeConn((2,), RuntimeError(f"timeout on {ip}:5432"))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual((res["value"], res["verdict"]), (2.0, "breach"))  # 量到的数不许变成「没查到」
        self.assertIsNone(res["error_message"])
        self.assertIn("RuntimeError", res["detail"]["error"])
        self.assertNotIn(ip, res["detail"]["error"])

    def test_missing_title_or_key_column_is_a_detail_error_not_misread(self):
        conn = DetailFakeConn((2,), (["foo", "bar"], [("x", "y")]))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual(res["verdict"], "breach")
        self.assertIn("缺列", res["detail"]["error"])

    def test_value_failure_skips_detail_query(self):
        conn = DetailFakeConn(RuntimeError("down"), (["title", "key"], [("x", "y")]))
        res = A.run_check(self._check(), lambda db: conn)
        self.assertEqual(res["verdict"], "error")
        self.assertIsNone(res["detail"])
        self.assertNotIn(self.DETAIL_SQL, conn.executed)

    def test_validate_rejects_bad_detail_sql(self):
        A.validate_contract([self._check()])
        for bad in ("", "  ", None, 3):
            with self.assertRaises(ValueError, msg=bad):
                A.validate_contract([check(detail_sql=bad)])
        watchdog_check = {
            "id": "watchdog.rule_z", "name": "人话名", "layer": "pipeline",
            "owner": "crawler/ops_watchdog.py", "rule": "Z", "normal": "== 0",
            "severity": "warn", "why": "为什么", "action": "怎么办", "source": "watchdog",
            "detail_sql": "select 1",
        }
        with self.assertRaises(ValueError):
            A.validate_contract([watchdog_check])


class MokaSameJobTwoEntriesContractTest(unittest.TestCase):
    """2026-09-23：299 个 Moka 岗同时挂在两个入口下，按网址长相认身份的老规则 H 一条没报。"""

    def setUp(self):
        self.c = {c["id"]: c for c in A.load_contract()}["jobs.moka_same_job_two_entries"]

    def test_declared_as_a_per_source_yellow_uncalibrated_data_check(self):
        c = self.c
        self.assertEqual((c["layer"], c["db"]), ("data", "jobs"))
        self.assertIn(c["severity"], ("info", "warn"))  # 单个源的问题最多黄灯，不许染红
        self.assertIs(c["calibrated"], False)
        self.assertEqual(c["covers"], ["jd_url"])
        self.assertTrue(A.evaluate_normal(1, c["normal"]))   # 东方财富那一对是有意保留的
        self.assertFalse(A.evaluate_normal(2, c["normal"]))  # 再多一份就该报

    def test_counts_by_job_number_not_by_mokahr_host(self):
        """Moka 的自有域名皮（recruit.pg.com.cn、talent.catl.com…）路径同形；只数 mokahr.com 会漏掉
        宝洁那种「同一个岗在 mokahr 与自有域名各一份」的重复（2026-09-23 真库实测到 1 对）。"""
        sql = " ".join(self.c["sql"].lower().split())
        self.assertNotIn("mokahr.com", sql)
        self.assertIn("#/job/", sql)
        self.assertIn("count(distinct entry)", sql)
        self.assertIn("job_no is not null", sql)  # 抽不出编号的行不许被算成重复

    def test_names_the_offending_pairs(self):
        detail = " ".join(self.c["detail_sql"].lower().split())
        self.assertIn(" as title", detail)
        self.assertIn(" as key", detail)
        # 有意保留的那一对要排最后：晨报 ⑦ 只点第一处，排前面会把真该处理的那一对挤掉
        self.assertIn("order by (k.entry_a is not null)", detail)


class RowShapeTest(unittest.TestCase):
    def test_result_row_has_every_ledger_column(self):
        res = A.run_check(check(calibrated=False), lambda db: FakeConn((0.2,)))
        for col in ("check_id", "run_date", "layer", "severity", "value", "normal",
                    "verdict", "calibrated", "measured_at", "error_message", "duration_ms", "detail"):
            self.assertIn(col, res)
        self.assertFalse(res["calibrated"])
        self.assertIsNone(res["detail"])  # SQL 类检查恒不写明细

    def test_exit_code_only_fails_when_ledger_write_fails(self):
        self.assertEqual(A.exit_code(written=True), 0)
        self.assertEqual(A.exit_code(written=False), 1)


if __name__ == "__main__":
    unittest.main()
