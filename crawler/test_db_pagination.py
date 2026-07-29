"""回归守卫：读 sources 全表的地方必须分页拉全量，且每页带稳定排序键。

2026-07-14 线上真事故（app 侧同 bug 已在 0072b75 修）：sources 越过 PostgREST 单次 select 的
1000 行硬顶（2026-07-20 实测 total=1121 / enabled=1079）→ 不分页只拿到前 1000 行：
  · db.get_sources() 是每日抓取主入口（run.py）的源清单来源 → 1079 个 enabled 源里 79 个
    每天根本没被抓到，且无 ORDER BY 时 Postgres 不保证行序 → 每次漏的还是不同的 79 个；
  · coverage / insight_backlog / auto_discover_overseas 同样拿到残缺集合。
每页必须带 .order("id")：跨请求翻页时无 ORDER BY 会重复取同一行 + 漏掉另一行。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402

import db  # noqa: E402


class _FakeQuery:
    """模拟 PostgREST：单次最多返回 1000 行，超出必须靠 range() 分页。

    过滤器（eq/in_/ilike）按调用顺序记录并真的施加到 rows 上，好让测试断言「分页没吃掉过滤条件」。
    """

    PAGE_CAP = 1000

    def __init__(self, rows, log):
        self.rows = rows
        self.log = log
        self._ordered = None
        self._start, self._end = 0, self.PAGE_CAP - 1

    def select(self, *_cols):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        vals = set(vals)
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def order(self, col, desc=False):
        self._ordered = col
        self.rows = sorted(self.rows, key=lambda r: r.get(col), reverse=desc)
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        self.log.append(self._ordered)
        page = self.rows[self._start:self._end + 1][:self.PAGE_CAP]

        class R:
            pass
        r = R()
        r.data = page
        return r


class _FakeSb:
    def __init__(self, rows):
        self.rows = rows
        self.order_log = []   # 每次 execute 时用的排序键，None = 没排序

    def table(self, _name):
        return _FakeQuery(list(self.rows), self.order_log)


def _sources(n, enabled_from=None):
    """n 行 sources；enabled_from 起（含）的行为 disabled，模拟「总数 > enabled 数」。"""
    return [{
        "id": f"{i:05d}",
        "company": f"C{i}",
        "enabled": enabled_from is None or i < enabled_from,
        "adapter_name": "moka" if i % 2 else "wt",
    } for i in range(n)]


class FetchAllRowsTest(unittest.TestCase):
    def test_reads_all_rows_beyond_postgrest_1000_row_cap(self):
        sb = _FakeSb(_sources(1121))
        rows = db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(len(rows), 1121, "尾部 121 行被 PostgREST 截断")

    def test_every_page_carries_stable_order_key(self):
        sb = _FakeSb(_sources(1121))
        db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertGreater(len(sb.order_log), 1, "超过 1000 行必须发多次请求")
        self.assertTrue(all(k == "id" for k in sb.order_log),
                        f"每页都必须带稳定排序键，实际 {sb.order_log}")

    def test_stops_without_extra_request_when_under_cap(self):
        sb = _FakeSb(_sources(10))
        rows = db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(len(rows), 10)
        self.assertEqual(len(sb.order_log), 1, "不足一页时不该多打一次空请求")

    def test_exact_multiple_of_page_size_terminates(self):
        sb = _FakeSb(_sources(2000))
        rows = db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(len(rows), 2000)

    def test_filters_survive_pagination(self):
        sb = _FakeSb(_sources(1121, enabled_from=1079))
        rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("*").eq("enabled", True))
        self.assertEqual(len(rows), 1079, "分页不能吃掉 .eq 过滤条件")
        self.assertTrue(all(r["enabled"] for r in rows))


class SupabaseReadRetryTest(unittest.TestCase):
    """读 Supabase 的网络抖动必须重试，不能让整个 CI 分片 exit 1。

    2026-07-28 线上（run 30363519599，enrich-backlog 的 hotjob 片）：读 sources 时
    `httpx.ConnectError: [Errno 104] Connection reset by peer` 直接冒泡 → 整片挂，
    而同一时刻其余 11 片读得好好的 = 单次 TCP 抖动，不是 Supabase 挂了。
    香港库那条路（jobs_db.get_conn）2026-07-26 已加同类重试，Supabase 这条当时漏了。"""

    def setUp(self):
        # 测试里不要真 sleep 掉 17 秒
        self._orig_sleep = db.time.sleep
        db.time.sleep = lambda _s: None

    def tearDown(self):
        db.time.sleep = self._orig_sleep

    def _flaky_sb(self, rows, fail_times, exc):
        """返回 (fake supabase, state)；前 fail_times 次 execute 抛 exc，之后正常返回。
        state["n"] = execute 被调用的总次数（用来断言重试了几次）。"""
        state = {"n": 0}

        class Q(_FakeQuery):
            def execute(self):
                state["n"] += 1
                if state["n"] <= fail_times:
                    raise exc
                return super().execute()

        class Sb(_FakeSb):
            def table(self, _name):
                return Q(list(self.rows), self.order_log)

        return Sb(rows), state

    def test_retries_transient_connect_reset_then_succeeds(self):
        sb, state = self._flaky_sb(
            _sources(10), fail_times=2,
            exc=httpx.ConnectError("[Errno 104] Connection reset by peer"))
        rows = db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(len(rows), 10, "重试后应拿到完整数据")
        self.assertEqual(state["n"], 3, "应在第 3 次尝试成功（前 2 次抖动）")

    def test_gives_up_after_attempt_cap_and_raises_original(self):
        sb, state = self._flaky_sb(
            _sources(10), fail_times=99,
            exc=httpx.ConnectError("[Errno 104] Connection reset by peer"))
        with self.assertRaises(httpx.ConnectError):
            db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(state["n"], db._READ_ATTEMPTS, "重试次数应等于 _READ_ATTEMPTS")

    def test_does_not_retry_non_network_errors(self):
        """PostgREST 的业务错（权限/SQL/4xx）重试多少次都是同样的错，只会拖慢失败。"""
        sb, state = self._flaky_sb(_sources(10), fail_times=99, exc=ValueError("bad query"))
        with self.assertRaises(ValueError):
            db.fetch_all_rows(lambda: sb.table("sources").select("*"))
        self.assertEqual(state["n"], 1, "非网络错不该重试")

    def test_retry_rebuilds_query_so_filters_are_not_stacked(self):
        """builder 有状态：重试若复用同一个 builder，range/order 会叠加 → 拿到错的页。"""
        sb, _ = self._flaky_sb(
            _sources(1121, enabled_from=1079), fail_times=1,
            exc=httpx.ReadError("boom"))
        rows = db.fetch_all_rows(
            lambda: sb.table("sources").select("*").eq("enabled", True))
        self.assertEqual(len(rows), 1079, "重试后过滤+分页结果应和没抖动时一致")
        self.assertTrue(all(r["enabled"] for r in rows))


class GetSourcesPaginationTest(unittest.TestCase):
    """run.py 每日抓取主入口的源清单来源——漏行 = 那些源当天根本没被抓。"""

    def test_returns_all_enabled_sources_beyond_1000(self):
        sb = _FakeSb(_sources(1121, enabled_from=1079))
        rows = db.get_sources(sb)
        self.assertEqual(len(rows), 1079, "enabled 1079 > 1000，不分页会漏掉 79 个源")
        self.assertTrue(all(r["enabled"] for r in rows), "不能把 disabled 源也抓进来")
        self.assertTrue(all(k == "id" for k in sb.order_log),
                        f"每页都必须带稳定排序键，实际 {sb.order_log}")


if __name__ == "__main__":
    unittest.main()
