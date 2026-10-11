"""rename_job_company.py 的契约：dry-run 绝不写、apply 只动「前缀 ∧ 旧名」、参数绑定、前缀转义。"""
import contextlib
import io
import unittest

try:
    import rename_job_company as R
    from rename_job_company import like_prefix, load_rename_map, parse_args, run, run_map
except ModuleNotFoundError:
    from crawler import rename_job_company as R
    from crawler.rename_job_company import like_prefix, load_rename_map, parse_args, run, run_map


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

    def test_parse_args_map_file_is_exclusive_with_prefix_mode(self):
        self.assertEqual(parse_args(["--map-file", "x.json"]).map_file, "x.json")
        with self.assertRaises(SystemExit):
            parse_args(["--map-file", "x.json", "--from", "a"])
        with self.assertRaises(SystemExit):  # 什么都不给
            parse_args([])
        with self.assertRaises(SystemExit):  # 前缀模式缺一个
            parse_args(["--url-prefix", PREFIX, "--from", "a"])
        with self.assertRaises(SystemExit):  # 演练和真写不能同时给
            parse_args(["--map-file", "x.json", "--apply", "--rehearse"])
        with self.assertRaises(SystemExit):  # 演练只属于批量模式
            parse_args(["--url-prefix", PREFIX, "--from", "a", "--to", "b", "--rehearse"])
        self.assertTrue(parse_args(["--map-file", "x.json", "--rehearse"]).rehearse)


# ── 批量模式（--map-file）──────────────────────────────────────────────────────────
class MapCursor:
    """按 SQL 开头分发的假游标。jobs = [(id, company, title, location, jd_url, status)]。

    它只模拟流程（事务边界、谁先谁后、护栏拦不拦），**不证明 SQL 本身是对的**——SQL 靠 --rehearse 在真库上验，
    以及下面 SqlContractTest 对着 schema.sql 钉住的那几条。
    """

    def __init__(self, jobs):
        self.jobs = [list(j) for j in jobs]
        self.map = {}
        self.log = []          # 留底表
        self.executed = []
        self.rowcount = 0
        self._result = []
        self.in_tx = False
        self.fail_on_update = False

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self.executed.append(flat)
        low = flat.lower()
        if low.startswith("create temp table") or low.startswith("create table") or low.startswith("set local"):
            return
        if low.startswith("delete from _rename_map"):
            self.map = {}
        elif low.startswith("insert into _rename_map"):
            self.map[params[0]] = params[1]
        elif low.startswith("select m.old_name"):
            counts = {}
            for _id, company, _t, _l, _u, status in self.jobs:
                if company in self.map:
                    key = (company, self.map[company], status)
                    counts[key] = counts.get(key, 0) + 1
            self._result = [(o, n, s, c) for (o, n, s), c in sorted(counts.items())]
        elif low.startswith("select count(*) from ("):
            groups = {}
            names = set(self.map) | set(self.map.values())
            for _id, company, title, loc, url, _s in self.jobs:
                if company not in names or title is None or loc is None or url is None:
                    continue
                key = (self.map.get(company, company), title, loc, url)
                g = groups.setdefault(key, [0, 0])
                g[0] += 1
                g[1] += company in self.map
            self._result = [(sum(1 for n, renamed in groups.values() if n > 1 and renamed > 0),)]
        elif low.startswith("select count(*) from jobs j join _rename_map"):
            self._result = [(sum(1 for j in self.jobs if j[1] in self.map),)]
        elif low == "begin":
            self.in_tx = True
            self._snapshot = ([list(j) for j in self.jobs], list(self.log))
        elif low == "commit":
            self.in_tx = False
        elif low == "rollback":
            self.jobs, self.log = self._snapshot
            self.in_tx = False
        elif low.startswith("with renamed as ( update jobs j set company = m.new_name"):
            assert self.in_tx, "改名 + 留底必须在事务里"
            if self.fail_on_update:
                raise RuntimeError("canceling statement due to lock timeout")
            batch = params[0]
            seen = {(r[0], r[3]) for r in self.log}
            updated = logged = 0
            for j in self.jobs:
                if j[1] in self.map:
                    old, new = j[1], self.map[j[1]]
                    j[1] = new
                    updated += 1
                    if (j[0], batch) not in seen:
                        self.log.append((j[0], old, new, batch))
                        logged += 1
            self._result = [(updated, logged)]
        else:
            raise AssertionError(f"没料到的 SQL：{flat[:80]}")

    def fetchall(self):
        return self._result


U = "https://wecruit.hotjob.cn/SUx/pb/posDetail.html?postId="
MAP_JOBS = [
    ("1", "TCL 校招", "算法工程师", "深圳", U + "1&postType=campus", "active"),
    ("2", "TCL 校招", "硬件工程师", "惠州", U + "2&postType=campus", "removed"),
    ("3", "TCL 实习", "算法实习生", "深圳", U + "3&postType=intern", "active"),
    ("4", "TCL", "算法工程师", "深圳", U + "4&postType=society", "active"),   # 同标题同地点、链接不同 → 不撞
    ("5", "别家公司 校招", "算法工程师", "深圳", U + "5", "active"),            # 不在清单里 → 不能碰
]

# read_state 的返回：(还叫旧名的源名, 新名在 sources 里出现的个数, 在飞的抓取条数)
READY = lambda pairs: ([], 1, 0)  # noqa: E731


def _write_map(tmp, renames, batch="b1"):
    import json
    import os
    path = os.path.join(tmp, "map.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"batch": batch, "renames": renames}, f, ensure_ascii=False)
    return path


class MapModeTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = _write_map(self._tmp.name, [{"from": "TCL 校招", "to": "TCL"}, {"from": "TCL 实习", "to": "TCL"}])
        self._out = io.StringIO()
        self._quiet = contextlib.redirect_stdout(self._out)
        self._quiet.__enter__()
        self.addCleanup(self._quiet.__exit__, None, None, None)

    def _names(self, cur):
        return [j[1] for j in cur.jobs]

    def test_dry_run_reports_and_never_writes(self):
        cur = MapCursor(MAP_JOBS)
        self.assertEqual(run_map(cur, self.path, read_state=READY), 0)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])
        self.assertFalse(any(s.lower().startswith(("with renamed", "begin")) for s in cur.executed))
        self.assertIn("共 3 行", self._out.getvalue())

    def test_dry_run_warns_about_what_would_block_apply(self):
        cur = MapCursor(MAP_JOBS)
        self.assertEqual(run_map(cur, self.path, read_state=lambda pairs: (["TCL 校招"], 1, 3)), 0)
        out = self._out.getvalue()
        self.assertIn("现在 --apply 会被拦", out)
        self.assertIn("TCL 校招", out)
        self.assertIn("3 条抓取正在跑", out)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])

    def test_apply_renames_and_logs_only_listed_names_in_one_statement(self):
        cur = MapCursor(MAP_JOBS)
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=READY), 0)
        self.assertEqual(self._names(cur), ["TCL", "TCL", "TCL", "TCL", "别家公司 校招"])
        # 留底记的是改名前的名字，三种状态的行都记
        self.assertEqual(sorted(cur.log), [("1", "TCL 校招", "TCL", "b1"), ("2", "TCL 校招", "TCL", "b1"),
                                           ("3", "TCL 实习", "TCL", "b1")])
        tx = [s.split(" ")[0].lower() for s in cur.executed if s.lower().startswith(("begin", "with renamed", "commit"))]
        self.assertEqual(tx, ["begin", "with", "commit"])
        self.assertIn("回读：仍叫旧名的行 0", self._out.getvalue())

    def test_rehearse_runs_the_real_statement_then_leaves_nothing(self):
        cur = MapCursor(MAP_JOBS)
        # 演练不受护栏约束（它什么都不留），所以哪怕源名还没改也能跑
        self.assertEqual(run_map(cur, self.path, rehearse=True, read_state=lambda pairs: (["TCL 校招"], 1, 2)), 0)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])
        self.assertEqual(cur.log, [])
        self.assertTrue(any(s.lower().startswith("with renamed") for s in cur.executed))
        self.assertEqual(cur.executed[-1], "rollback")
        self.assertIn("改名 3 行、留底 3 行", self._out.getvalue())

    def test_apply_refuses_while_sources_still_carry_old_names(self):
        cur = MapCursor(MAP_JOBS)
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=lambda pairs: (["TCL 校招"], 1, 0)), 2)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])
        self.assertEqual(cur.log, [])

    def test_apply_refuses_when_no_new_name_is_visible_in_sources(self):
        # 读回 0 行（连错库 / 没权限）时「没有旧名」是假象：新名也一个都看不到 → 当作读失败
        cur = MapCursor(MAP_JOBS)
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=lambda pairs: ([], 0, 0)), 2)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])

    def test_apply_refuses_while_a_crawl_is_in_flight_unless_allowed(self):
        cur = MapCursor(MAP_JOBS)
        busy = lambda pairs: ([], 1, 4)  # noqa: E731
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=busy), 2)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])
        self.assertEqual(run_map(cur, self.path, apply=True, allow_in_flight=True, read_state=busy), 0)
        self.assertEqual(self._names(cur)[:3], ["TCL", "TCL", "TCL"])

    def test_source_read_failure_propagates_instead_of_passing(self):
        def boom(pairs):
            raise RuntimeError("Supabase 读失败")
        cur = MapCursor(MAP_JOBS)
        with self.assertRaises(RuntimeError):
            run_map(cur, self.path, apply=True, read_state=boom)
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])

    def test_unique_key_collision_blocks_the_whole_batch(self):
        # 本名下已有一行 标题 / 地点 / 链接 全同（哪怕已下架）→ update 会被唯一键打回，必须事先拦住
        jobs = MAP_JOBS + [("6", "TCL", "算法工程师", "深圳", U + "1&postType=campus", "removed")]
        for kwargs in ({}, {"apply": True}, {"rehearse": True}):
            cur = MapCursor(jobs)
            self.assertEqual(run_map(cur, self.path, read_state=READY, **kwargs), 2)
            self.assertEqual(self._names(cur), [j[1] for j in jobs])
            self.assertFalse(any(s.lower().startswith("begin") for s in cur.executed))

    def test_two_old_names_collapsing_onto_each_other_count_as_collision(self):
        # 「TCL 校招」「TCL 实习」各有一行 标题 / 地点 / 链接 全同 → 都改成 TCL 后互相撞
        jobs = [("1", "TCL 校招", "管培生", "深圳", U + "9", "active"), ("2", "TCL 实习", "管培生", "深圳", U + "9", "removed")]
        cur = MapCursor(jobs)
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=READY), 2)

    def test_null_location_rows_do_not_count_as_collision(self):
        # 唯一约束把 NULL 当互不相同：地点为空的两行改成同名不会撞
        jobs = [("1", "TCL 校招", "算法工程师", None, U + "1", "active"),
                ("2", "TCL", "算法工程师", None, U + "1", "removed")]
        cur = MapCursor(jobs)
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=READY), 0)
        self.assertEqual(self._names(cur), ["TCL", "TCL"])

    def test_failed_statement_rolls_back_and_reraises_the_original_error(self):
        cur = MapCursor(MAP_JOBS)
        cur.fail_on_update = True
        with self.assertRaisesRegex(RuntimeError, "lock timeout"):
            run_map(cur, self.path, apply=True, read_state=READY)
        self.assertEqual(cur.log, [])
        self.assertEqual(self._names(cur), [j[1] for j in MAP_JOBS])
        self.assertEqual(cur.executed[-1], "rollback")

    def test_rerun_after_write_back_renames_again_and_keeps_the_first_log_row(self):
        # 在飞的抓取轮把一行写回旧名 → 同一批次重跑：改名照做，留底不重复记（保留首次的旧名）
        cur = MapCursor(MAP_JOBS)
        run_map(cur, self.path, apply=True, read_state=READY)
        cur.jobs[0][1] = "TCL 校招"
        self.assertEqual(run_map(cur, self.path, apply=True, read_state=READY), 0)
        self.assertEqual(cur.jobs[0][1], "TCL")
        self.assertEqual(len(cur.log), 3)
        self.assertIn("留底 0 行少于改名 1 行", self._out.getvalue())


class RenameMapFileTest(unittest.TestCase):
    def _load(self, renames, batch="b1"):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            return load_rename_map(_write_map(tmp, renames, batch))

    def test_rejects_bad_maps_before_touching_db(self):
        bad = [
            [],                                                              # 空
            [{"from": "A", "to": "A"}],                                      # 无事可做
            [{"from": "A", "to": "B"}, {"from": "A", "to": "C"}],            # 旧名重复
            [{"from": "A", "to": "B"}, {"from": "B", "to": "C"}],            # 链式：结果取决于顺序
            [{"from": "A ", "to": "B"}],                                     # 首尾空白
            [{"from": "", "to": "B"}],
        ]
        for renames in bad:
            with self.assertRaises(ValueError, msg=str(renames)):
                self._load(renames)
        with self.assertRaises(ValueError):
            self._load([{"from": "A", "to": "B"}], batch="")

    def test_shipped_channel_suffix_map_is_well_formed(self):
        import os
        import re
        here = os.path.dirname(os.path.abspath(__file__))
        batch, pairs = load_rename_map(os.path.join(here, "company_renames", "20261011_channel_suffix.json"))
        self.assertEqual(batch, "20261011_channel_suffix")
        suffix = re.compile(r"\s+(校招|实习|社招)$")
        explicit = {"神州信息—AI实习生": "神州信息", "豪迈集团—职能实习生": "豪迈集团"}
        for old, new in pairs:
            self.assertEqual(new, explicit.get(old) or suffix.sub("", old), old)
            self.assertNotRegex(new, r"校招|实习|社招")


class SqlContractTest(unittest.TestCase):
    """假游标证明不了 SQL。这里把几条 SQL 对着 schema.sql 钉住，其余靠 --rehearse 在真库上跑。"""

    @staticmethod
    def _schema():
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "jobs-db", "schema.sql"), encoding="utf-8") as f:
            return " ".join(f.read().split())

    def test_log_table_ddl_matches_schema_file(self):
        self.assertIn(" ".join(R.RENAME_LOG_DDL.split()), self._schema())

    def test_collision_check_groups_by_exactly_the_unique_key_columns(self):
        import re
        m = re.search(r"constraint jobs_company_title_location_jd_url_key unique \(([^)]*)\)", self._schema())
        self.assertIsNotNone(m, "jobs 的四列唯一约束不在 schema.sql 里了：撞键检查要跟着改")
        cols = [c.strip() for c in m.group(1).split(",")]
        self.assertEqual(cols, ["company", "title", "location", "jd_url"])
        sql = " ".join(R._MAP_COLLISION_SQL.split())
        # 第一列是改名后的公司名，其余三列原样；并且只在有行被改名的组上报
        self.assertIn("select coalesce(m.new_name, j.company), j.title, j.location, j.jd_url", sql)
        self.assertIn("group by 1, 2, 3, 4", sql)
        self.assertIn("having count(*) > 1 and count(m.old_name) > 0", sql)
        for col in cols[1:]:  # NULL 在唯一约束里互不相同
            self.assertIn(f"j.{col} is not null", sql)

    def test_rename_and_log_are_one_statement(self):
        sql = " ".join(R._MAP_APPLY_SQL.split())
        self.assertTrue(sql.startswith("with renamed as ( update jobs j set company = m.new_name from _rename_map m "
                                       "where j.company = m.old_name returning j.id, m.old_name, m.new_name )"))
        self.assertIn("insert into job_company_renames (job_id, old_company, new_company, batch) "
                      "select id, old_name, new_name, %s from renamed on conflict (job_id, batch) do nothing", sql)
        self.assertEqual(sql.count("%s"), 1)


if __name__ == "__main__":
    unittest.main()
