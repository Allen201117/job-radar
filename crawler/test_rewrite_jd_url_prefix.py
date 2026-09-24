"""rewrite_jd_url_prefix.py 的契约：只动 active ∧ 前缀 ∧ 公司；冲突行跳过；dry-run 绝不写；参数绑定；幂等。

SQL 本身（前缀替换、触发器重算 canonical、冲突判定）在香港真库上 begin/rollback 回放过（2026-09-24 长安：
412 + 13 行可改、0 冲突，canonical / apply_url 跟着对，重跑 0 行）；这里钉住调用形状与护栏。"""
import contextlib
import io
import json
import os
import unittest

try:
    import rewrite_jd_url_prefix as rw
    from rename_job_company import like_prefix
except ModuleNotFoundError:
    from crawler import rewrite_jd_url_prefix as rw
    from crawler.rename_job_company import like_prefix

FROM = "https://changan.zhiye.com/jobs/zwxq"
TO = "https://changan.zhiye.com/social/detail"


class FakeCursor:
    def __init__(self, planned, conflicts):
        self.counts, self.executed, self.rowcount = (planned, conflicts), [], 0

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), dict(params)))
        if not sql.lstrip().lower().startswith("select"):
            self.rowcount = self.counts[0]

    def fetchone(self):
        return self.counts


class RunTest(unittest.TestCase):
    def setUp(self):
        self._q = contextlib.redirect_stdout(io.StringIO())
        self._q.__enter__()

    def tearDown(self):
        self._q.__exit__(None, None, None)

    def test_dry_run_counts_and_never_writes(self):
        cur = FakeCursor(412, 0)
        self.assertEqual(rw.run(cur, FROM, TO, "长安汽车 Changan"), (412, 0, None))
        self.assertEqual(len(cur.executed), 1)

    def test_apply_binds_params_scopes_to_active_and_skips_conflicts(self):
        cur = FakeCursor(412, 3)
        self.assertEqual(rw.run(cur, FROM, TO, "长安汽车 Changan", apply=True), (412, 3, 412))
        sql, params = cur.executed[-1]
        self.assertTrue(sql.startswith("update jobs j set jd_url ="))
        self.assertIn("where j.status = 'active' and j.company = %(company)s and j.jd_url like %(pattern)s", sql)
        self.assertIn("and not (exists", sql, "冲突行必须跳过，不能让整批撞唯一索引回滚")
        self.assertIn("public.canonicalize_jd_url(", sql, "冲突要按改完后的 canonical 判，和唯一索引同口径")
        self.assertIn("k.status = 'active' and k.id <> j.id", sql)
        self.assertEqual(params, {"from": FROM, "to": TO, "company": "长安汽车 Changan",
                                  "pattern": like_prefix(FROM)})

    def test_nothing_to_do_does_not_write(self):
        cur = FakeCursor(0, 2)
        self.assertEqual(rw.run(cur, FROM, TO, "长安汽车 Changan", apply=True), (0, 2, None))
        self.assertEqual(len(cur.executed), 1)

    def test_like_pattern_escapes_wildcards(self):
        """前缀里的 _ / % 必须转义，否则 LIKE 会把别的门户也吞进来。"""
        self.assertEqual(rw.params_for("https://a.b/x_y", TO, "c")["pattern"], "https://a.b/x\\_y%")


class ParseArgsTest(unittest.TestCase):
    def _args(self, frm, to):
        return ["--company", "c", "--from-prefix", frm, "--to-prefix", to]

    def test_valid(self):
        a = rw.parse_args(self._args(FROM, TO))
        self.assertFalse(a.apply)

    def test_rejects_non_https_or_bare_host(self):
        for frm, to in (("http://changan.zhiye.com/jobs/zwxq", TO), (FROM, "https://")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                rw.parse_args(self._args(frm, to))

    def test_rejects_same_and_self_extending_prefix(self):
        """to 以 from 开头 = 改完的行下次还会被再改一遍（不幂等）。"""
        for frm, to in ((FROM, FROM), (FROM, FROM + "/x")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                rw.parse_args(self._args(frm, to))


class ChanganRouteTest(unittest.TestCase):
    def test_changan_route_is_a_detail_page_not_the_list(self):
        """2026-09-24 真渲染：/jobs/zwxq?jobAdId= 落在「全部职位」列表页；/social/detail 渲染岗位详情。"""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beisen_routes.json")
        with open(path, encoding="utf-8") as f:
            routes = json.load(f)
        self.assertEqual(routes["changan.zhiye.com"], "https://changan.zhiye.com/social/detail")


if __name__ == "__main__":
    unittest.main()
