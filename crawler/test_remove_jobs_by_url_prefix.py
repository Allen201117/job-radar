"""remove_jobs_by_url_prefix.py 的契约：只动 active ∧ 前缀 ∧ 公司；dry-run 绝不写；参数绑定。"""
import contextlib
import io
import unittest

try:
    from remove_jobs_by_url_prefix import run, parse_args
    from rename_job_company import like_prefix
except ModuleNotFoundError:
    from crawler.remove_jobs_by_url_prefix import run, parse_args
    from crawler.rename_job_company import like_prefix

PREFIX = "https://tbea.hotjob.cn/wt/TBEA/"
ROWS = [  # (company, jd_url, status)
    ("新疆特变电工集团", PREFIX + "mobweb/position/detail?postIdsAry=1", "active"),
    ("新疆特变电工集团", PREFIX + "mobweb/position/detail?postIdsAry=2", "active"),
    ("新疆特变电工集团", PREFIX + "mobweb/position/detail?postIdsAry=3", "expired"),   # 非 active 不动
    ("新疆特变电工集团", "https://wecruit.hotjob.cn/SU612f/pb/posDetail.html?postId=4", "active"),  # 别的门户不动
    ("别的公司", PREFIX + "mobweb/position/detail?postIdsAry=5", "active"),            # 别的公司不动
]


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.executed, self.rowcount = rows, [], 0

    def _hit(self, company, pattern):
        raw = pattern[:-1].replace("\\", "")
        return [r for r in self.rows if r[2] == "active" and r[0] == company and r[1].startswith(raw)]

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), list(params)))
        company, pattern = params
        n = len(self._hit(company, pattern))
        if sql.lstrip().lower().startswith("select"):
            self._one = (n,)
        else:
            self.rowcount = n

    def fetchone(self):
        return self._one


class RunTest(unittest.TestCase):
    def setUp(self):
        self._q = contextlib.redirect_stdout(io.StringIO())
        self._q.__enter__()

    def tearDown(self):
        self._q.__exit__(None, None, None)

    def test_dry_run_counts_only_active_prefix_company_and_never_writes(self):
        cur = FakeCursor(ROWS)
        self.assertEqual(run(cur, PREFIX, "新疆特变电工集团"), (2, None))
        self.assertEqual(len(cur.executed), 1)

    def test_apply_binds_params_and_only_flips_active(self):
        cur = FakeCursor(ROWS)
        self.assertEqual(run(cur, PREFIX, "新疆特变电工集团", apply=True), (2, 2))
        sql, params = cur.executed[-1]
        self.assertIn("set status = 'removed' where status = 'active'", sql)
        self.assertEqual(params, ["新疆特变电工集团", like_prefix(PREFIX)])

    def test_apply_with_no_hits_does_not_write(self):
        cur = FakeCursor(ROWS)
        self.assertEqual(run(cur, PREFIX, "没有的公司", apply=True), (0, None))
        self.assertEqual(len(cur.executed), 1)

    def test_parse_args_requires_full_prefix(self):
        with self.assertRaises(SystemExit):
            parse_args(["--url-prefix", "https://", "--company", "x"])
        self.assertFalse(parse_args(["--url-prefix", PREFIX, "--company", "x"]).apply)


if __name__ == "__main__":
    unittest.main()
