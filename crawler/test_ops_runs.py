"""ops_runs 台账写入单测：写入失败必须被吞掉，不能影响原 workflow。"""
import unittest
from datetime import datetime, timezone

import ops_runs


class _FakeQuery:
    def __init__(self, store, fail=False):
        self.store = store
        self.fail = fail

    def insert(self, row):
        if self.fail:
            raise RuntimeError("ledger unavailable")
        self.store.append(row)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("ledger unavailable")
        return type("R", (), {"data": []})()


class _FakeSB:
    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    def table(self, name):
        self.table_name = name
        return _FakeQuery(self.rows, self.fail)


class OpsRunsTest(unittest.TestCase):
    def test_records_shanghai_run_date_and_metrics(self):
        sb = _FakeSB()
        ok = ops_runs.record_ops_run(
            sb,
            "liveness_sweep",
            {"checked": 12, "expired": 3},
            status="partial",
            started_at="2026-06-21T16:30:00+00:00",
            finished_at="2026-06-21T16:40:00+00:00",
        )
        self.assertTrue(ok)
        self.assertEqual(sb.table_name, "ops_runs")
        self.assertEqual(sb.rows[0]["run_date"], "2026-06-22")
        self.assertEqual(sb.rows[0]["metrics"], {"checked": 12, "expired": 3})
        self.assertEqual(sb.rows[0]["status"], "partial")

    def test_write_failure_is_swallowed(self):
        self.assertFalse(
            ops_runs.record_ops_run(
                _FakeSB(fail=True),
                "enrich_backlog",
                {"checked": 1},
                started_at=datetime(2026, 6, 22, tzinfo=timezone.utc),
            )
        )

    def test_status_from_counts(self):
        self.assertEqual(ops_runs.status_from_counts(0, 0), "success")
        self.assertEqual(ops_runs.status_from_counts(10, 0), "success")
        self.assertEqual(ops_runs.status_from_counts(10, 2), "partial")
        self.assertEqual(ops_runs.status_from_counts(10, 10), "failed")


if __name__ == "__main__":
    unittest.main()


class SkipBreakdownTest(unittest.TestCase):
    """skip 原因必须进台账 —— 「跑绿了 + 零产出」而看不出卡在哪，是本项目明令禁止的失败静默。

    实锤：campus_official_backlog 连续多天记 {"draft":0,"verified":0,"companies_processed":40}
    且 status=success，40 家一家没产出，台账里却完全看不出是「没有官方域」还是「页面无信号」
    还是「判官没通过」—— 只能本地复现才能判因。
    """

    def test_按原因聚合并加统一前缀(self):
        results = [
            {"company": "A", "skipped": "no_official_host"},
            {"company": "B", "skipped": "no_official_host"},
            {"company": "C", "skipped": "no_campus_page_signal"},
            {"company": "D", "verified": 1},
        ]
        self.assertEqual(
            ops_runs.skip_breakdown(results),
            {"skip_no_official_host": 2, "skip_no_campus_page_signal": 1},
        )

    def test_没有跳过时返回空字典_不往台账里塞噪音(self):
        self.assertEqual(ops_runs.skip_breakdown([{"company": "A", "verified": 1}]), {})
        self.assertEqual(ops_runs.skip_breakdown([]), {})
        self.assertEqual(ops_runs.skip_breakdown(None), {})

    def test_额外的布尔标记也能当跳过原因计入(self):
        # campus_cycle_backlog 的「搜索额度耗尽」是布尔字段，不是 skipped 字符串
        results = [{"company": "A", "budget_exhausted": True}, {"company": "B", "skipped": "no_company"}]
        self.assertEqual(
            ops_runs.skip_breakdown(results, flags=("budget_exhausted",)),
            {"skip_budget_exhausted": 1, "skip_no_company": 1},
        )

    def test_脏值不炸_原因名归一(self):
        results = [
            {"company": "A", "skipped": "  no_company  "},
            {"company": "B", "skipped": ""},          # 空串不算跳过
            {"company": "C", "skipped": None},
            {"company": "D"},
            "不是字典",
        ]
        self.assertEqual(ops_runs.skip_breakdown(results), {"skip_no_company": 1})

    def test_原因数量封顶_防止把台账撑爆(self):
        # 原因来自代码里的有限枚举，但 crash:<ExcName> 这类是开放集合，必须封顶
        results = [{"company": str(i), "skipped": f"crash:E{i}"} for i in range(30)]
        out = ops_runs.skip_breakdown(results)
        self.assertLessEqual(len(out), ops_runs.SKIP_BREAKDOWN_MAX_KEYS + 1)
        self.assertEqual(sum(out.values()), 30, "封顶后总数仍须守恒（多的并进 skip_other）")
        self.assertIn("skip_other", out)
