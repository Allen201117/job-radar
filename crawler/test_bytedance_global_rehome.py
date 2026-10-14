"""字节全球站存量挪行工具的单测：只测处置规划与安全闸（纯函数，不连库、不打网络）。"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import bytedance_global_rehome as R
from adapters.bytedance import BytedanceAdapter, BytedanceCampusAdapter, BytedanceGlobalAdapter


def _cn(pid, board="experienced"):
    return f"https://jobs.bytedance.com/{board}/position/{pid}/detail"


def _global(pid):
    return f"https://joinbytedance.com/search/{pid}"


class PlanRehomeTest(unittest.TestCase):
    def test_only_rows_live_on_global_and_absent_from_cn_portals_move(self):
        lib = [
            ("a", _cn("1")),            # 全球站在招、中文站没有 → 挪
            ("b", _cn("2", "campus")),  # 同上（校招源名下）→ 挪
            ("c", _cn("3")),            # 中文站在招 → 不动
            ("d", _cn("4")),            # 哪个公开门户都不在 → 不动（留给缺席撤岗）
        ]
        actions = R.plan_rehome(lib, {"1": _global("1"), "2": _global("2")}, {"3"})

        self.assertEqual([(a[0], a[1], a[3]) for a in actions], [
            ("rehome", "a", _global("1")),
            ("rehome", "b", _global("2")),
            ("keep_on_cn_portal", "c", None),
            ("keep_not_global", "d", None),
        ])

    def test_row_on_both_cn_portal_and_global_stays_put(self):
        # 中文站链接能打开就别动它：挪走之后中文站那条源下一轮会把同一个岗当新岗再插一行。
        actions = R.plan_rehome([("a", _cn("1"))], {"1": _global("1")}, {"1"})

        self.assertEqual(actions[0][0], "keep_on_cn_portal")

    def test_job_missing_from_global_urls_is_not_moved(self):
        # global_urls 由调用方给：只含全球站 adapter 解析后留下的岗（地区白名单在 adapter 里过，
        # 见 test_bytedance.GlobalSiteTest）。不在里面的——比如东京的岗——一律不动。
        actions = R.plan_rehome([("a", _cn("9"))], {}, set())

        self.assertEqual(actions[0][0], "keep_not_global")

    def test_unrecognised_links_are_never_touched(self):
        lib = [("a", "https://bytedance.jobs.feishu.cn/society/position/1/detail"), ("b", ""), ("c", None),
               ("d", _global("1"))]
        actions = R.plan_rehome(lib, {"1": _global("1")}, set())

        self.assertEqual({a[0] for a in actions}, {"keep_unparsed"})

    def test_post_id_reads_both_link_shapes(self):
        self.assertEqual(R.post_id_of(_cn("7509262740803930376", "campus")), "7509262740803930376")
        self.assertEqual(R.post_id_of(_global("7509262740803930376")), "7509262740803930376")
        self.assertIsNone(R.post_id_of("https://jobs.bytedance.com/experienced/position"))


class SafetyGateTest(unittest.TestCase):
    def test_writes_only_when_every_gate_passes(self):
        ok, why = R.rehome_allowed(1000, 20000, lists_complete=True, global_source_enabled=False)
        self.assertTrue(ok, why)

    def test_incomplete_list_blocks(self):
        # 中文站列表没抓全时，「不在中文站列表里」不成立——会把中文站上在招的岗挪走。
        ok, why = R.rehome_allowed(1000, 20000, lists_complete=False, global_source_enabled=False)
        self.assertFalse(ok)
        self.assertIn("抓全", why)

    def test_enabled_global_source_blocks(self):
        ok, why = R.rehome_allowed(1000, 20000, lists_complete=True, global_source_enabled=True)
        self.assertFalse(ok)

    def test_unexpectedly_large_move_blocks(self):
        ok, why = R.rehome_allowed(4000, 20000, lists_complete=True, global_source_enabled=False)
        self.assertFalse(ok)
        self.assertIn("15%", why)

    def test_nothing_to_move_is_allowed(self):
        self.assertTrue(R.rehome_allowed(0, 0, lists_complete=True, global_source_enabled=False)[0])


class ApplyStatementTest(unittest.TestCase):
    """写库只有一条语句：连接是 autocommit，拆成多条就不再是「要么全挪、要么一行不动」。"""

    def test_single_statement_and_skip_when_target_link_is_taken(self):
        executed = []

        class Cur:
            rowcount = 2

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=None):
                executed.append((sql, params))

        class Conn:
            def cursor(self):
                return Cur()

        actions = [("rehome", "id-1", _cn("1"), _global("1")), ("rehome", "id-2", _cn("2"), _global("2")),
                   ("rehome", "id-3", _cn("3"), _global("3")), ("keep_not_global", "id-4", _cn("4"), None)]
        out = R.apply_rehome(Conn(), "src-global", ["src-social", "src-campus"], actions)

        # 这里只钉「一条语句 + 参数对齐」，假游标验不了 SQL。语句本身在真库上彩排过（2026-10-12：一个事务里
        # 整条执行 → UPDATE 969 → 回读 canonical 跟着变、首见时间不变 → ROLLBACK 后一行不剩）。
        self.assertEqual(len(executed), 1)
        sql, params = executed[0]
        self.assertIn("update jobs", sql)
        self.assertIn("j.status = 'active'", sql)
        self.assertIn("j.source_id = any(", sql)   # 只动中文站两条源名下的行
        self.assertEqual(params[0], ["id-1", "id-2", "id-3"])
        self.assertEqual(params[1], [_global("1"), _global("2"), _global("3")])
        self.assertEqual(params[2], "src-global")
        self.assertEqual(params[3], ["src-social", "src-campus"])
        self.assertEqual(out, {"rehomed": 2, "skipped_taken": 1})

    def test_nothing_to_do_issues_no_statement(self):
        class Conn:
            def cursor(self):
                raise AssertionError("不该开游标")

        self.assertEqual(R.apply_rehome(Conn(), "s", ["a", "b"], [("keep_not_global", "x", _cn("1"), None)]),
                         {"rehomed": 0, "skipped_taken": 0})


class LinkShapeTest(unittest.TestCase):
    def test_link_patterns_follow_the_adapters_detail_templates(self):
        # 这里的两条链接正则是 adapter detail_template 的第二份：adapter 改了链接形状，这里必须跟着红。
        for cls in (BytedanceAdapter, BytedanceCampusAdapter, BytedanceGlobalAdapter):
            self.assertEqual(R.post_id_of(cls.detail_template.format(id="7509262740803930376")),
                             "7509262740803930376", cls.name)
        # 只有中文站两种链接算「可以挪的行」；全球站链接的行已经在目的地了。
        self.assertIsNotNone(R._CN_URL_RE.match(BytedanceAdapter.detail_template.format(id="1")))
        self.assertIsNotNone(R._CN_URL_RE.match(BytedanceCampusAdapter.detail_template.format(id="1")))
        self.assertIsNone(R._CN_URL_RE.match(BytedanceGlobalAdapter.detail_template.format(id="1")))


class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._rows = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.executed.append(sql)
        text = " ".join(sql.split())
        if text.startswith("select id::text, jd_url"):
            self._rows = list(self.conn.lib)
        elif "update jobs" in text:
            self.rowcount = len(params[0])
        elif text.startswith("select count(*)"):
            self._rows = [(len(self.conn.lib),)]

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


class _Conn:
    def __init__(self, lib):
        self.lib = lib
        self.executed = []
        self.closed = False

    def cursor(self):
        return _Cur(self)

    def close(self):
        self.closed = True


class MainFlowTest(unittest.TestCase):
    """main() 的编排：假源表 / 假列表 / 假库，验「什么时候写、什么时候不写、退出码」。"""

    SOURCES = [
        {"id": "src-social", "adapter_name": "bytedance", "enabled": True, "regions": ["CN"],
         "source_url": "https://jobs.bytedance.com/experienced/position", "company": "字节跳动"},
        {"id": "src-campus", "adapter_name": "bytedance_campus", "enabled": True, "regions": ["CN"],
         "source_url": "https://jobs.bytedance.com/campus/position", "company": "字节跳动"},
        {"id": "src-global", "adapter_name": "bytedance_global", "enabled": False,
         "regions": ["CN", "US", "SG", "Remote"], "source_url": "https://joinbytedance.com/search", "company": "字节跳动"},
        {"id": "other", "adapter_name": "feishu", "enabled": True, "regions": ["CN"],
         "source_url": "https://x.jobs.feishu.cn/index/position", "company": "别家"},
    ]
    # 2 行要挪、1 行哪都不在、30 行在中文站上在招（要挪的占比得低于 15% 那道闸）。
    ON_CN = [str(n) for n in range(100, 130)]
    LIB = ([("id-1", _cn("1"), "src-social", "US"), ("id-2", _cn("2", "campus"), "src-campus", "SG"),
            ("id-4", _cn("4"), "src-social", "∅")]
           + [(f"id-{n}", _cn(n), "src-social", "CN") for n in ON_CN])

    def _run(self, argv, *, sources=None, complete=True):
        from types import SimpleNamespace as NS
        portals = {
            BytedanceGlobalAdapter: ([NS(jd_url=_global("1")), NS(jd_url=_global("2"))], complete, 2),
            BytedanceCampusAdapter: ([], True, 0),
            BytedanceAdapter: ([NS(jd_url=_cn(n)) for n in self.ON_CN], True, len(self.ON_CN)),
        }
        fetch_calls = []

        def fake_fetch(cls, source):
            fetch_calls.append(cls.name)
            return portals[cls]

        conn = _Conn(self.LIB)
        code = 0
        with mock.patch.object(R.db, "get_supabase", return_value=object()), \
                mock.patch.object(R.db, "fetch_all_rows", return_value=sources or self.SOURCES), \
                mock.patch.object(R, "_fetch_portal", side_effect=fake_fetch), \
                mock.patch.object(R.jobs_db, "get_conn", return_value=conn), \
                mock.patch.object(sys, "argv", ["rehome"] + argv), \
                mock.patch("builtins.print"):
            try:
                R.main()
            except SystemExit as e:
                code = e.code
        updates = [s for s in conn.executed if "update jobs" in s]
        return code, updates, fetch_calls, conn

    def test_dry_run_never_writes(self):
        code, updates, fetch_calls, conn = self._run([])
        self.assertEqual((code, updates), (0, []))
        self.assertEqual(len(fetch_calls), 3)
        self.assertTrue(conn.closed)

    def test_apply_writes_exactly_one_statement(self):
        code, updates, _calls, _conn = self._run(["--apply"])
        self.assertEqual(code, 0)
        self.assertEqual(len(updates), 1)

    def test_unexpectedly_large_share_blocks_apply(self):
        # 库里只剩 3 行、其中 2 行要挪（67%）：超过 15% 那道闸，不写。
        with mock.patch.object(MainFlowTest, "LIB", self.LIB[:3]):
            code, updates, _calls, _conn = self._run(["--apply"])
        self.assertEqual((code, updates), (2, []))

    def test_incomplete_list_blocks_apply(self):
        code, updates, _calls, _conn = self._run(["--apply"], complete=False)
        self.assertEqual((code, updates), (2, []))

    def test_enabled_global_source_stops_before_fetching_anything(self):
        sources = [dict(s, enabled=True) if s["adapter_name"] == "bytedance_global" else s for s in self.SOURCES]
        code, updates, fetch_calls, _conn = self._run(["--apply"], sources=sources)
        self.assertEqual((code, updates, fetch_calls), (2, [], []))

    def test_missing_source_row_stops(self):
        sources = [s for s in self.SOURCES if s["adapter_name"] != "bytedance_global"]
        code, updates, fetch_calls, _conn = self._run(["--apply"], sources=sources)
        self.assertEqual((code, updates, fetch_calls), (2, [], []))


if __name__ == "__main__":
    unittest.main()
