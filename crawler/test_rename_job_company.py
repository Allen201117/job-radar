"""rename_job_company.py 的契约：dry-run 绝不写、apply 只动「前缀 ∧ 旧名」、参数绑定、前缀转义。"""
import contextlib
import io
import unittest

try:
    from rename_job_company import like_prefix, run, parse_args
except ModuleNotFoundError:
    from crawler.rename_job_company import like_prefix, run, parse_args


PREFIX = "https://wecruit.hotjob.cn/SU612f55eebef57c0616450aa2/"


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows  # (company, jd_url, status)
        self.executed = []
        self.rowcount = 0
        self._result = []

    def execute(self, sql, params=None):
        params = list(params or [])
        self.executed.append((" ".join(sql.split()), params))
        if sql.lstrip().lower().startswith("select"):
            old, pattern = params
            hit = [r for r in self.rows if r[0] == old and r[1].startswith(pattern[:-1].replace("\\", ""))]
            counts = {}
            for r in hit:
                counts[r[2]] = counts.get(r[2], 0) + 1
            self._result = sorted(counts.items())
            return
        new, old, pattern = params
        self.rowcount = sum(1 for r in self.rows if r[0] == old and r[1].startswith(pattern[:-1].replace("\\", "")))

    def fetchall(self):
        return self._result


ROWS = [
    ("领益智造 Lingyi 实习", PREFIX + "pb/posDetail.html?postId=1&postType=intern", "active"),
    ("领益智造 Lingyi 实习", PREFIX + "pb/posDetail.html?postId=2&postType=intern", "expired"),
    # 同名但不在这个前缀下（真领益智造哪天接上）→ 不能碰
    ("领益智造 Lingyi 实习", "https://lingyi.hotjob.cn/SUother/pb/posDetail.html?postId=9", "active"),
    # 同前缀但名字不同（社招那条源）→ 不能碰
    ("领益智造 Lingyi", PREFIX + "pb/posDetail.html?postId=3&postType=social", "active"),
]


class RunTest(unittest.TestCase):
    def setUp(self):
        self._quiet = contextlib.redirect_stdout(io.StringIO())
        self._quiet.__enter__()

    def tearDown(self):
        self._quiet.__exit__(None, None, None)

    def test_dry_run_counts_by_status_and_never_writes(self):
        cur = FakeCursor(ROWS)
        report = run(cur, PREFIX, "领益智造 Lingyi 实习", "新疆特变电工集团 实习")
        self.assertEqual(report, {"active": 1, "expired": 1})
        self.assertTrue(all(sql.startswith("select") for sql, _ in cur.executed))

    def test_apply_only_touches_prefix_and_old_name(self):
        cur = FakeCursor(ROWS)
        report = run(cur, PREFIX, "领益智造 Lingyi 实习", "新疆特变电工集团 实习", apply=True)
        self.assertEqual(report["_updated"], 2)
        sql, params = cur.executed[-1]
        self.assertTrue(sql.startswith("update jobs set company = %s where company = %s and jd_url like %s"))
        self.assertEqual(params, ["新疆特变电工集团 实习", "领益智造 Lingyi 实习", like_prefix(PREFIX)])

    def test_apply_with_no_hits_does_not_write(self):
        cur = FakeCursor(ROWS)
        report = run(cur, PREFIX, "不存在的名字", "X", apply=True)
        self.assertEqual(report, {})
        self.assertEqual(len(cur.executed), 1)


class HelpersTest(unittest.TestCase):
    def test_like_prefix_escapes_wildcards(self):
        self.assertEqual(like_prefix("https://a.b/x_y%"), "https://a.b/x\\_y\\%%")

    def test_parse_args_rejects_short_prefix_and_noop(self):
        with self.assertRaises(SystemExit):
            parse_args(["--url-prefix", "https://", "--from", "a", "--to", "b"])
        with self.assertRaises(SystemExit):
            parse_args(["--url-prefix", PREFIX, "--from", "a", "--to", "a"])
        args = parse_args(["--url-prefix", PREFIX, "--from", "a", "--to", "b"])
        self.assertFalse(args.apply)


if __name__ == "__main__":
    unittest.main()
