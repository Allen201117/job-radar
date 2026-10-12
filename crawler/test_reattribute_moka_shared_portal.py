"""reattribute_moka_shared_portal 的契约：逐行按标题判、两个方向都报、认不出的不动、
dry-run 绝不写、apply 前过护栏、改名与留底同一条语句（不打真网络、不连库）。"""
import contextlib
import io
import re
import unittest
from datetime import date, datetime, timezone
from unittest import mock

import reattribute_moka_shared_portal as R

PORTAL = "https://app.mokahr.com/campus-recruitment/crland/168540"
HOME, WXSH = "华润置地", "华润万象生活"
U = PORTAL + "#/job/"


def _rows():
    """(id, jd_url, company, status, title, location)"""
    return [
        ("1", U + "a", HOME, "active", "万象生-推广岗（商业-厦门)", "厦门"),          # 万象生活的岗挂在置地 → 改
        ("2", U + "b", HOME, "active", "百匠新人-土建工程岗(开发-北京)", "北京"),      # 置地的岗 → 已正确
        ("3", U + "c", WXSH, "expired", "万悦生-运营管理岗(酒管-杭州)", "杭州"),       # 反方向：置地的岗挂成万象生活 → 改回
        ("4", U + "d", HOME, "active", "百匠新人-人力资源岗(武汉)", "武汉"),           # 认不出 → 不动
        ("5", U + "e", WXSH, "active", "万悦生-客户服务岗（物业-重庆)", "重庆"),       # 已正确
        ("6", U + "f", "别的名字", "active", "万象生-营运岗（商业-天津)", "天津"),     # 第三个公司名 → 不动、单独报
        # 门户号更长的另一个门户、同租户的社招门户：前缀护栏必须挡住
        ("7", PORTAL + "1#/job/g", HOME, "active", "万象生-推广岗（商业-厦门)", "厦门"),
        ("8", "https://app.mokahr.com/social-recruitment/crland/143066#/job/h", WXSH, "active",
         "百匠新人-土建工程岗(开发-北京)", "北京"),
    ]


class FakeJobsCursor:
    """内存里的 jobs 表：只认脚本会发的那几条语句。"""

    def __init__(self, rows):
        self.rows = [list(r) for r in rows]
        self.executed = []
        self.log = []          # 留底表
        self._result = []
        self._snapshot = None
        self.fail_on_apply = None

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        params = list(params or [])
        self.executed.append((flat, params))
        low = flat.lower()
        if low == "begin":
            self._snapshot = ([list(r) for r in self.rows], list(self.log))
        elif low == "rollback":
            self.rows, self.log = self._snapshot
        elif low.startswith("select id, jd_url, company, status, title from jobs where jd_url like"):
            prefix = params[0][:-1].replace("\\", "")
            self._result = [tuple(r[:5]) for r in self.rows if r[1].startswith(prefix)]
        elif low.startswith("select count(*) from jobs j join jobs k"):
            ids, new = params
            hits = sum(1 for j in self.rows if j[0] in ids for k in self.rows
                       if k[0] != j[0] and k[2] == new and (k[1], k[4], k[5]) == (j[1], j[4], j[5])
                       and None not in (j[4], j[5]))
            self._result = [(hits,)]
        elif low.startswith("with renamed as"):
            if self.fail_on_apply:
                raise self.fail_on_apply
            new, ids, old, log_old, log_new, batch = params
            hit = [r for r in self.rows if r[0] in ids and r[2] == old]
            for r in hit:
                r[2] = new
                self.log.append((r[0], log_old, log_new, batch))
            self._result = [(len(hit), len(hit))]
        elif low.startswith("select company, status, count(*) from jobs where jd_url like"):
            prefix = params[0][:-1].replace("\\", "")
            counts = {}
            for r in self.rows:
                if r[1].startswith(prefix):
                    counts[(r[2], r[3])] = counts.get((r[2], r[3]), 0) + 1
            self._result = [(c, s, n) for (c, s), n in sorted(counts.items())]

    def fetchall(self):
        return self._result

    def company_of(self, job_id):
        return next(r[2] for r in self.rows if r[0] == job_id)

    def writes(self):
        return [sql for sql, _p in self.executed if sql.lower().startswith(("update", "with renamed", "insert", "delete"))]


def _ok_state(_prefix):
    return [HOME], 0


class _Quiet(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self._cm = contextlib.redirect_stdout(self.out)
        self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)


class PlanTest(unittest.TestCase):
    def test_home_and_owners_come_from_the_registry(self):
        self.assertEqual(R.portal_companies(PORTAL), (HOME, frozenset({WXSH})))

    def test_both_directions_unresolved_and_foreign_names(self):
        rows = [r[:5] for r in _rows()[:6]]
        changes, stats, unresolved = R.plan(rows, PORTAL)
        self.assertEqual(changes, [("1", HOME, WXSH, "active"), ("3", WXSH, HOME, "expired")])
        self.assertEqual(dict(stats), {"already_correct": 2, "other_company": 1})
        self.assertEqual(unresolved, [("百匠新人-人力资源岗(武汉)", HOME, "active")])

    def test_unresolved_row_under_the_other_name_is_not_moved_home(self):
        """认不出 ≠ 属于本家：挂在万象生活名下的认不出的行也不许顺手改回置地。"""
        changes, _stats, unresolved = R.plan([("1", U + "a", WXSH, "active", "管培生")], PORTAL)
        self.assertEqual(changes, [])
        self.assertEqual(len(unresolved), 1)


class RunTest(_Quiet):
    def test_dry_run_reports_each_direction_and_never_writes(self):
        cur = FakeJobsCursor(_rows())
        self.assertEqual(R.run(cur, PORTAL, read_state=_ok_state), 0)
        self.assertEqual(cur.writes(), [])
        text = self.out.getvalue()
        self.assertIn(f"{HOME} → {WXSH}：1", text)
        self.assertIn(f"{WXSH} → {HOME}：1", text)
        self.assertIn("认不出：百匠新人-人力资源岗(武汉)", text)
        self.assertIn("下共 6 行", text)          # 门户号更长的门户与社招门户不在范围里

    def test_zero_direction_is_still_printed(self):
        cur = FakeJobsCursor([r for r in _rows() if r[0] in ("1", "2")])
        R.run(cur, PORTAL, read_state=_ok_state)
        self.assertIn(f"{WXSH} → {HOME}：0", self.out.getvalue())

    def test_no_rows_under_the_prefix_is_failure_not_a_green_noop(self):
        """前缀写错 / 连错了库：不许绿着什么都没做。"""
        cur = FakeJobsCursor([r for r in _rows() if r[0] in ("7", "8")])
        self.assertEqual(R.run(cur, PORTAL, apply=True, read_state=_ok_state), 2)
        self.assertEqual(cur.writes(), [])

    def test_apply_moves_only_judged_rows_inside_the_portal_and_logs_them(self):
        cur = FakeJobsCursor(_rows())
        self.assertEqual(R.run(cur, PORTAL, apply=True, batch="b1", read_state=_ok_state), 0)
        self.assertEqual({i: cur.company_of(i) for i in "12345678"}, {
            "1": WXSH, "2": HOME, "3": HOME, "4": HOME, "5": WXSH, "6": "别的名字", "7": HOME, "8": WXSH})
        self.assertEqual(sorted(cur.log), [("1", HOME, WXSH, "b1"), ("3", WXSH, HOME, "b1")])
        self.assertIn("backfill-recruitment-category", self.out.getvalue())

    def test_apply_statement_is_guarded_by_ids_and_old_name(self):
        cur = FakeJobsCursor(_rows())
        R.run(cur, PORTAL, apply=True, batch="b1", read_state=_ok_state)
        applied = [p for sql, p in cur.executed if sql.startswith("with renamed as")]
        # 参数顺序：新名、岗位 id、旧名（update 的条件），再是留底的 旧名、新名、批次。按 (旧名, 新名) 排序逐组执行。
        self.assertEqual(applied, [[HOME, ["3"], WXSH, WXSH, HOME, "b1"], [WXSH, ["1"], HOME, HOME, WXSH, "b1"]])

    def test_rehearse_runs_for_real_then_leaves_nothing_even_with_a_crawl_in_flight(self):
        cur = FakeJobsCursor(_rows())
        self.assertEqual(R.run(cur, PORTAL, rehearse=True, read_state=lambda _p: ([HOME], 3)), 0)
        self.assertEqual(cur.company_of("1"), HOME)
        self.assertEqual(cur.log, [])
        self.assertIn("rollback", [sql for sql, _p in cur.executed])
        self.assertNotIn("commit", [sql for sql, _p in cur.executed])
        self.assertIn("改名 2 行", self.out.getvalue())

    def test_apply_refuses_while_a_crawl_is_in_flight_unless_allowed(self):
        cur = FakeJobsCursor(_rows())
        self.assertEqual(R.run(cur, PORTAL, apply=True, read_state=lambda _p: ([HOME], 2)), 2)
        self.assertEqual(cur.writes(), [])
        self.assertEqual(R.run(cur, PORTAL, apply=True, allow_in_flight=True,
                               read_state=lambda _p: ([HOME], 2)), 0)
        self.assertEqual(cur.company_of("1"), WXSH)

    def test_apply_and_rehearse_refuse_when_the_source_is_not_named_like_the_registered_home(self):
        for state in (["华润置地有限公司"], [], [HOME, WXSH], [WXSH]):
            for kw in ({"apply": True}, {"rehearse": True}, {"apply": True, "allow_in_flight": True}):
                cur = FakeJobsCursor(_rows())
                self.assertEqual(R.run(cur, PORTAL, read_state=lambda _p, s=state: (s, 0), **kw), 2, (state, kw))
                self.assertEqual(cur.writes(), [])

    def test_source_read_failure_propagates_instead_of_passing(self):
        def boom(_prefix):
            raise ConnectionError("supabase down")
        cur = FakeJobsCursor(_rows())
        with self.assertRaises(ConnectionError):
            R.run(cur, PORTAL, apply=True, read_state=boom)
        self.assertEqual(cur.writes(), [])

    def test_unique_key_collision_blocks_the_whole_batch(self):
        """同一个链接、标题、地点已经有一行挂在新名下：改过去会撞唯一键，整批不动。"""
        twin = ("9", U + "a", WXSH, "removed", "万象生-推广岗（商业-厦门)", "厦门")
        cur = FakeJobsCursor(_rows() + [twin])
        self.assertEqual(R.run(cur, PORTAL, apply=True, read_state=_ok_state), 2)
        self.assertEqual(cur.writes(), [])
        self.assertIn("唯一键 1 行", self.out.getvalue())

    def test_twin_under_another_name_or_with_null_location_is_not_a_collision(self):
        rows = _rows() + [("9", U + "a", "别的名字", "removed", "万象生-推广岗（商业-厦门)", "厦门"),
                          ("10", U + "x", HOME, "active", "万象生-推广岗（商业-福州)", None),
                          ("11", U + "x", WXSH, "removed", "万象生-推广岗（商业-福州)", None)]
        cur = FakeJobsCursor(rows)
        self.assertEqual(R.run(cur, PORTAL, apply=True, read_state=_ok_state), 0)

    def test_failed_statement_rolls_back_and_reraises(self):
        cur = FakeJobsCursor(_rows())
        cur.fail_on_apply = RuntimeError("lock timeout")
        with self.assertRaises(RuntimeError):
            R.run(cur, PORTAL, apply=True, read_state=_ok_state)
        self.assertEqual(cur.company_of("1"), HOME)
        self.assertEqual([sql for sql, _p in cur.executed][-1], "rollback")

    def test_nothing_to_change_does_not_touch_supabase_or_db(self):
        def boom(_prefix):
            raise AssertionError("没有要改的行时不该去读 Supabase")
        cur = FakeJobsCursor([r for r in _rows() if r[0] in ("2", "5")])
        self.assertEqual(R.run(cur, PORTAL, apply=True, read_state=boom), 0)
        self.assertEqual(cur.writes(), [])


class SourceStateTest(unittest.TestCase):
    def _state(self, sources, in_flight):
        import db
        with mock.patch.object(db, "get_supabase", return_value=mock.MagicMock()), \
                mock.patch.object(db, "fetch_all_rows", side_effect=[sources, in_flight]):
            return R.source_state(PORTAL, now=datetime(2026, 10, 12, 13, 0, tzinfo=timezone.utc))

    def test_only_enabled_sources_of_this_portal_count(self):
        sources = [
            {"company": HOME, "source_url": PORTAL, "enabled": True},
            {"company": HOME, "source_url": "https://app.mokahr.com/campus-recruitment/crland/143067", "enabled": False},
            {"company": WXSH, "source_url": "https://app.mokahr.com/social-recruitment/crland/143066", "enabled": True},
            {"company": "别家", "source_url": PORTAL + "1", "enabled": True},
            {"company": "停用的同门户源", "source_url": PORTAL, "enabled": False},
        ]
        self.assertEqual(self._state(sources, [{"id": 1}, {"id": 2}]), ([HOME], 2))

    def test_same_portal_under_two_spellings_is_reported_as_two_sources(self):
        """同一个门户挂了两条启用源（别名写法）：两条都报出来，由调用方拒绝。"""
        sources = [{"company": HOME, "source_url": PORTAL, "enabled": True},
                   {"company": WXSH, "source_url": "https://app.mokahr.com/campus_apply/crland/168540#/jobs", "enabled": True}]
        self.assertEqual(self._state(sources, []), ([WXSH, HOME] if WXSH < HOME else [HOME, WXSH], 0))


class ArgsTest(unittest.TestCase):
    def _fails(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            R.parse_args(argv)

    def test_refuses_unregistered_portal(self):
        self._fails(["--url-prefix", "https://app.mokahr.com/social-recruitment/crland/143066"])
        self._fails(["--url-prefix", PORTAL + "1"])

    def test_refuses_prefix_that_is_not_exactly_the_portal_page(self):
        """多带一段路径照样认得出门户，拼出来的 LIKE 却一行都匹配不到。"""
        for bad in (PORTAL + "/jobs", PORTAL + "#/jobs", PORTAL + "?a=1", PORTAL.replace("https://", "http://"),
                    "app.mokahr.com/campus-recruitment/crland/168540"):
            self._fails(["--url-prefix", bad])
        self._fails(["--url-prefix", PORTAL, "--apply", "--rehearse"])

    def test_accepts_the_registered_portal(self):
        args = R.parse_args(["--url-prefix", PORTAL + "/"])
        self.assertEqual((args.url_prefix, args.apply, args.rehearse), (PORTAL, False, False))


class SqlContractTest(unittest.TestCase):
    """假游标证明不了 SQL：把形状钉住，其余靠 --rehearse 在真库上跑。"""

    def test_portal_pattern_ends_at_the_hash(self):
        pattern = R.portal_pattern(PORTAL)
        self.assertTrue(pattern.endswith("/crland/168540#%"), pattern)
        self.assertNotIn("168540%", pattern)      # 没有 # 的话会扫到 1685401

    def test_rename_and_log_are_one_statement_guarded_by_old_name(self):
        sql = " ".join(R._APPLY_SQL.split())
        self.assertTrue(sql.startswith("with renamed as ( update jobs set company = %s "
                                       "where id = any(%s::uuid[]) and company = %s returning id )"))
        self.assertIn("insert into job_company_renames (job_id, old_company, new_company, batch) "
                      "select id, %s, %s, %s from renamed on conflict (job_id, batch) do nothing", sql)
        self.assertEqual(sql.count("%s"), 6)

    def test_collision_check_compares_exactly_the_unique_key_columns(self):
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "jobs-db", "schema.sql"), encoding="utf-8") as f:
            schema = " ".join(f.read().split())
        m = re.search(r"constraint jobs_company_title_location_jd_url_key unique \(([^)]*)\)", schema)
        self.assertIsNotNone(m, "jobs 的四列唯一约束不在 schema.sql 里了：撞键检查要跟着改")
        self.assertEqual([c.strip() for c in m.group(1).split(",")], ["company", "title", "location", "jd_url"])
        sql = " ".join(R._COLLISION_SQL.split())
        for col in ("jd_url", "title", "location"):
            self.assertIn(f"k.{col} = j.{col}", sql)
        self.assertTrue(sql.endswith("where j.id = any(%s::uuid[]) and k.company = %s"))

    def test_default_batch_names_the_portal_and_the_day(self):
        self.assertEqual(R.default_batch(PORTAL, date(2026, 10, 12)), "moka_shared_portal_crland_168540_20261012")


if __name__ == "__main__":
    unittest.main()
