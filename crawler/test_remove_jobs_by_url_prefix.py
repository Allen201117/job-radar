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


SHADOW = "https://app.mokahr.com/social-recruitment/zuoyebang/150144#"
KEEP = "https://app.mokahr.com/social-recruitment/zuoyebang/41328#"
TWIN_ROWS = [
    ("作业帮", SHADOW + "/job/aaa", "active"),              # 保留门户下有孪生 → 标
    ("作业帮", SHADOW + "/job/bbb", "active"),              # 只在影子门户 → 不动
    ("作业帮", SHADOW + "/job/ccc", "active"),              # 孪生行已不 active → 不算孪生
    ("作业帮 Zuoyebang", KEEP + "/job/aaa", "active"),
    ("作业帮 Zuoyebang", KEEP + "/job/ccc", "expired"),
]


def _raw(pattern):
    return pattern[:-1].replace("\\", "")


def _fragment(url):
    return url.split("#", 1)[1] if "#" in url else ""


class FakeCursor:
    def __init__(self, rows):
        self.rows, self.executed, self.rowcount = rows, [], 0

    def _hit(self, company, pattern, twin_pattern=None):
        hits = [r for r in self.rows if r[2] == "active" and r[0] == company and r[1].startswith(_raw(pattern))]
        if twin_pattern is None:
            return hits
        twins = {_fragment(r[1]) for r in self.rows if r[2] == "active" and r[1].startswith(_raw(twin_pattern))}
        return [r for r in hits if _fragment(r[1]) and _fragment(r[1]) in twins]

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), list(params)))
        n = len(self._hit(*params))
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


class OnlyTwinsTest(unittest.TestCase):
    """规则 H 的处置口径：只标「在保留门户下确有孪生行」的，只在影子门户出现的岗不要动。
    2026-09-23 作业帮 150144 198 个在招里 195 个在 41328 下有同一个 #/job/ id，另 3 个只在它下面。"""

    def setUp(self):
        self._q = contextlib.redirect_stdout(io.StringIO())
        self._q.__enter__()

    def tearDown(self):
        self._q.__exit__(None, None, None)

    def test_only_rows_with_active_twin_under_kept_portal(self):
        cur = FakeCursor(TWIN_ROWS)
        self.assertEqual(run(cur, SHADOW, "作业帮", apply=True, twins_under=KEEP), (1, 1))
        sql, params = cur.executed[-1]
        self.assertIn("split_part(jd_url, '#', 2) <> ''", sql, "没有 # 片段的行不许被当成孪生")
        self.assertIn("where k.status = 'active'", sql, "孪生行必须还在招")
        self.assertEqual(params, ["作业帮", like_prefix(SHADOW), like_prefix(KEEP)])

    def test_without_twins_under_flips_the_whole_prefix(self):
        self.assertEqual(run(FakeCursor(TWIN_ROWS), SHADOW, "作业帮", apply=True), (3, 3))

    def test_parse_args_rejects_overlapping_prefixes(self):
        base = ["--company", "x", "--url-prefix", "https://app.mokahr.com/campus_apply/zhihu"]
        with self.assertRaises(SystemExit):   # 保留门户 campus_apply/zhihu/3818 落在影子前缀里 → 会自己标自己
            parse_args(base + ["--only-twins-under", "https://app.mokahr.com/campus_apply/zhihu/3818#"])
        with self.assertRaises(SystemExit):
            parse_args(base + ["--only-twins-under", "https://"])
        args = parse_args(["--company", "x", "--url-prefix", SHADOW, "--only-twins-under", KEEP])
        self.assertEqual(args.only_twins_under, KEEP)


if __name__ == "__main__":
    unittest.main()
