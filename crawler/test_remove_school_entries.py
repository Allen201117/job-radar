"""remove_school_entries.py 的契约：判据只认 adapter 闸门、dry-run 绝不写、apply 只动确认过的 id。"""
import contextlib
import io
import unittest

try:
    from remove_school_entries import confirm_school_entries, run, parse_args
except ModuleNotFoundError:
    from crawler.remove_school_entries import confirm_school_entries, run, parse_args


EMPTY_WITH_REQ = "。\n\n【任职要求】\n。"

ROWS = [
    # (id, company, title, summary)
    ("a1", "中广核", "北京建筑大学", "。"),
    ("a2", "中广核", "清华大学深圳国际研究生院", EMPTY_WITH_REQ),
    ("a3", "中广核", "海外院校", "。"),
    # 只中「标题」不中「正文」：特变电工的真岗，正文完整 → 保住
    ("b1", "特变电工", "FPGA软件工程师-研究院", "1、参与FPGA技术需求分析，设计相应场景下FPGA方案；"),
    # 只中「正文」不中「标题」：三棵树薄卡 → 保住（薄卡按 CLAUDE.md §4 留库）
    ("c1", "三棵树", "行政接待类实习生", EMPTY_WITH_REQ),
    # SQL 粗筛会放过（标题含「大学」、正文为空），但 adapter 正则不认带逗号的标题 → 保住
    ("d1", "某公司", "北京大学，清华大学", "。"),
]


class FakeCursor:
    """只实现脚本用到的游标接口。select 按公司过滤回 ROWS；update 记下 SQL 与参数。"""

    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.rowcount = 0
        self._result = []

    def execute(self, sql, params=None):
        params = list(params or [])
        self.executed.append((" ".join(sql.split()), params))
        if sql.lstrip().lower().startswith("select"):
            companies = list(params[0]) if params else []
            self._result = [r for r in self.rows if not companies or r[1] in companies]
            return
        self.rowcount = len(params[0])

    def fetchall(self):
        return self._result


class ConfirmTest(unittest.TestCase):
    def test_only_intersection_of_institution_title_and_empty_body(self):
        picked = {r[0] for r in confirm_school_entries(ROWS)}
        self.assertEqual(picked, {"a1", "a2", "a3"})


class RunTest(unittest.TestCase):
    def setUp(self):
        self._quiet = contextlib.redirect_stdout(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)

    def test_dry_run_reports_per_company_and_never_writes(self):
        cur = FakeCursor(ROWS)
        report = run(cur, apply=False)
        self.assertEqual(report, {"中广核": 3})
        self.assertFalse(any("update" in sql.lower() for sql, _ in cur.executed))

    def test_candidate_select_scopes_to_active_wt_rows(self):
        cur = FakeCursor(ROWS)
        run(cur, apply=False)
        select_sql = cur.executed[0][0].lower()
        self.assertIn("status = 'active'", select_sql)
        self.assertIn("/wt/", select_sql)

    def test_apply_updates_only_confirmed_ids_to_removed(self):
        cur = FakeCursor(ROWS)
        report = run(cur, apply=True, companies=["中广核"])
        self.assertEqual(report, {"中广核": 3})
        writes = [(sql, params) for sql, params in cur.executed if sql.lower().startswith("update")]
        self.assertEqual(len(writes), 1)
        sql, params = writes[0]
        self.assertIn("status = 'removed'", sql)
        self.assertIn("status = 'active'", sql)   # 只翻 active，别把 expired/removed 也刷一遍
        self.assertEqual(sorted(params[0]), ["a1", "a2", "a3"])

    def test_company_filter_is_bound_not_interpolated(self):
        cur = FakeCursor(ROWS)
        run(cur, apply=False, companies=["中广核"])
        sql, params = cur.executed[0]
        self.assertNotIn("中广核", sql)
        self.assertEqual(params, [["中广核"]])


class ArgsTest(unittest.TestCase):
    def test_apply_requires_company(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parse_args(["--apply"])

    def test_check_is_the_default_and_explicit_flag_is_accepted(self):
        self.assertFalse(parse_args([]).apply)
        self.assertFalse(parse_args(["--check"]).apply)
        self.assertTrue(parse_args(["--apply", "--company", "中广核"]).apply)


if __name__ == "__main__":
    unittest.main()
