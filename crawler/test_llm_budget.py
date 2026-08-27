"""LLM 日顶守卫单测（纯函数 + mock supabase，不打网络/不碰真 DB/绝不调 LLM）。

盯死四条不变量：① 天花板按「全部非豁免 kind 之和」判，不是每个 kind 各给一份；② 跨天自动重置；
③ 豁免 kind 不计数、不受限、零 DB 往返；④ 计数读/写失败一律 fail-open 且不抛（主任务不受影响）。
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import llm_budget as B


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday():
    return (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()


class _FakeQuery:
    def __init__(self, sb):
        self.sb = sb
        self._op = None
        self._payload = None
        self._filters = {}

    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def upsert(self, row, **_k):
        self._op, self._payload = "upsert", dict(row)
        return self

    def execute(self):
        if self._op == "select":
            if self.sb.fail_read:
                raise RuntimeError("supabase read down")
            day = self._filters.get("day")
            rows = [dict(r) for r in self.sb.rows if day is None or r["day"] == day]
            return type("R", (), {"data": rows})()
        if self._op == "upsert":
            if self.sb.fail_write:
                raise RuntimeError("supabase write down")
            self.sb.writes.append(self._payload)
            for row in self.sb.rows:
                if row["kind"] == self._payload["kind"] and row["day"] == self._payload["day"]:
                    row.update(self._payload)
                    break
            else:
                self.sb.rows.append(dict(self._payload))
            return type("R", (), {"data": [self._payload]})()
        raise AssertionError(f"未预期的操作: {self._op}")


class _FakeSB:
    def __init__(self, rows=None, fail_read=False, fail_write=False):
        self.rows = [dict(r) for r in (rows or [])]
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.writes = []
        self.tables = []

    def table(self, name):
        self.tables.append(name)
        return _FakeQuery(self)


class _ExplodingSB:
    """任何 DB 触碰都炸——用来证明豁免 kind 走的是零 DB 往返的快路径。"""

    def table(self, *_a, **_k):
        raise AssertionError("豁免 kind 不该碰数据库")


class PureHelpersTest(unittest.TestCase):
    def test_parse_cap_falls_back_on_garbage(self):
        self.assertEqual(B.parse_cap("300"), 300)
        self.assertEqual(B.parse_cap(None), B.DEFAULT_DAILY_CAP)
        self.assertEqual(B.parse_cap(""), B.DEFAULT_DAILY_CAP)
        self.assertEqual(B.parse_cap("abc"), B.DEFAULT_DAILY_CAP)
        self.assertEqual(B.parse_cap("-5"), B.DEFAULT_DAILY_CAP)
        self.assertEqual(B.parse_cap("0"), 0)  # 0 = 全挡（与 search_budget 同口径），非「不限制」

    def test_allows_is_inclusive_at_cap_and_blocks_zero_cap(self):
        self.assertTrue(B.allows(9, 10))
        self.assertTrue(B.allows(9, 10, n=1))
        self.assertFalse(B.allows(10, 10))
        self.assertFalse(B.allows(9, 10, n=2))
        self.assertFalse(B.allows(0, 0))

    def test_sum_counted_skips_exempt_and_garbage(self):
        rows = [
            {"kind": "insight_t3", "used": 40},
            {"kind": "resume_parse", "used": 999},
            {"kind": "insight_draft", "used": "7"},
            {"kind": "broken", "used": "n/a"},
            None,
        ]
        self.assertEqual(B.sum_counted(rows, ("resume_parse",)), 47)

    def test_normalize_and_parse_kinds(self):
        self.assertEqual(B.normalize_kind("  Insight_T3 "), "insight_t3")
        self.assertEqual(B.normalize_kind(None), B.DEFAULT_KIND)
        self.assertEqual(B.parse_kinds(None), frozenset({"resume_parse"}))
        self.assertEqual(B.parse_kinds("a, B"), frozenset({"a", "b"}))
        self.assertEqual(B.parse_kinds(""), frozenset())  # 显式配空 = 谁都不豁免


class CheckAndConsumeTest(unittest.TestCase):
    def test_under_cap_allows_and_records(self):
        sb = _FakeSB()
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertEqual(sb.tables[0], "llm_usage")
        self.assertEqual(sb.writes[-1]["kind"], "insight_t3")
        self.assertEqual(sb.writes[-1]["day"], _today())
        self.assertEqual(sb.writes[-1]["used"], 1)
        # 再要一次 → 累加，不覆盖
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertEqual(sb.writes[-1]["used"], 2)

    def test_blocks_at_cap_without_writing(self):
        sb = _FakeSB([{"kind": "insight_t3", "day": _today(), "used": 10}])
        self.assertFalse(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertEqual(sb.writes, [])

    def test_cap_is_shared_across_non_exempt_kinds(self):
        """天花板 = 全部非豁免 kind 之和；否则 kind 一多总花费又没上限（等于没装闸）。"""
        sb = _FakeSB([
            {"kind": "insight_t3", "day": _today(), "used": 6},
            {"kind": "insight_draft", "day": _today(), "used": 4},
        ])
        self.assertFalse(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertFalse(B.check_and_consume(sb, kind="insight_draft", cap=10))
        self.assertEqual(sb.writes, [])

    def test_exempt_kind_never_touches_db(self):
        self.assertTrue(B.check_and_consume(_ExplodingSB(), kind="resume_parse", cap=1))

    def test_exempt_kind_usage_does_not_eat_budget(self):
        sb = _FakeSB([{"kind": "resume_parse", "day": _today(), "used": 999}])
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertEqual(sb.writes[-1]["used"], 1)

    def test_yesterday_usage_does_not_count(self):
        sb = _FakeSB([{"kind": "insight_t3", "day": _yesterday(), "used": 500}])
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=10))
        self.assertEqual(sb.writes[-1]["day"], _today())
        self.assertEqual(sb.writes[-1]["used"], 1)  # 新的一天从 0 起算

    def test_write_failure_is_swallowed_and_still_allows(self):
        sb = _FakeSB(fail_write=True)
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=10))  # 不抛、不挡主任务

    def test_read_failure_fails_open(self):
        sb = _FakeSB(fail_read=True)
        self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=1))

    def test_env_cap_is_honoured(self):
        sb = _FakeSB([{"kind": "insight_t3", "day": _today(), "used": 2}])
        with mock.patch.dict(os.environ, {B.CAP_ENV: "2"}, clear=False):
            self.assertFalse(B.check_and_consume(sb, kind="insight_t3"))
        with mock.patch.dict(os.environ, {B.CAP_ENV: "5"}, clear=False):
            self.assertTrue(B.check_and_consume(sb, kind="insight_t3"))
        self.assertEqual(sb.writes[-1]["used"], 3)

    def test_env_exempt_list_is_honoured(self):
        sb = _FakeSB([{"kind": "insight_t3", "day": _today(), "used": 99}])
        with mock.patch.dict(os.environ, {B.EXEMPT_ENV: "insight_t3"}, clear=False):
            self.assertTrue(B.is_exempt("insight_t3"))
            self.assertTrue(B.check_and_consume(sb, kind="insight_t3", cap=1))
        self.assertEqual(sb.writes, [])  # 豁免后连账都不记


class ObservabilityTest(unittest.TestCase):
    def test_used_today_and_remaining(self):
        sb = _FakeSB([
            {"kind": "insight_t3", "day": _today(), "used": 30},
            {"kind": "resume_parse", "day": _today(), "used": 500},
            {"kind": "insight_t3", "day": _yesterday(), "used": 200},
        ])
        self.assertEqual(B.used_today(sb), 30)                       # 豁免 + 昨天都不算
        self.assertEqual(B.used_today(sb, kind="insight_t3"), 30)
        self.assertEqual(B.remaining(sb, cap=100), 70)

    def test_remaining_on_read_failure_reports_full_cap(self):
        self.assertEqual(B.remaining(_FakeSB(fail_read=True), cap=42), 42)


if __name__ == "__main__":
    unittest.main()
