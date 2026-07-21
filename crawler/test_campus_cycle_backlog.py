"""校招往年时间线 B3 —— drain_one_company / select_cycle_targets / current_cohort 单测。
monkeypatch 掉一切网络/LLM/搜索（fetch_one_company / chat_json / judge_claim / router / 写库），
不打真实网络，验证「判官 → is_official_grounding → decide_cycle_status → 写库」这条官方源门链路
+ 幂等/冲突（verified 不覆盖、draft 不重复堆积）落到了实处。
"""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import campus_cycle_backlog as B  # noqa: E402


class _FakeRouter:
    def __init__(self, results, remaining=999):
        self._results = list(results)
        self._remaining = remaining

    def search(self, sb, query, top_k=8, client=None):
        return list(self._results)

    def remaining(self, sb):
        return self._remaining


class _FakeQuery:
    """极简 select/insert fake：支持 .select().eq().eq().order().range().limit().execute()
    与 .insert(row).execute()（写库记进 sb.inserted，供断言；不支持 update/upsert，B3 不需要）。"""

    def __init__(self, sb, table_name):
        self.sb = sb
        self.table_name = table_name
        self._filters = {}
        self._op = "select"
        self._insert_row = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, row):
        self._op = "insert"
        self._insert_row = row
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "insert":
            self.sb.inserted.setdefault(self.table_name, []).append(dict(self._insert_row))
            return type("R", (), {"data": [self._insert_row]})()
        rows = self.sb.canned.get(self.table_name, [])
        for col, val in self._filters.items():
            rows = [r for r in rows if r.get(col) == val]
        return type("R", (), {"data": rows})()


class FakeSB:
    def __init__(self, canned=None):
        self.canned = canned or {}   # {table_name: [rows]}
        self.inserted = {}           # {table_name: [inserted rows]}（写库台账，测试断言用）

    def table(self, name):
        return _FakeQuery(self, name)


def _fake_fetch_one_company(sb, company):
    return {"id": "co-1", "company": company}


class DrainOneCompanyTest(unittest.TestCase):
    def setUp(self):
        self._orig_router = B._ROUTER
        self._orig_fetch_one = B.fetch_one_company
        self._orig_chat_json = B.chat_json
        self._orig_judge = B.judge_claim
        self._orig_llm_config = B.llm_config
        B.fetch_one_company = _fake_fetch_one_company
        B.llm_config = lambda: {"configured": True}

    def tearDown(self):
        B._ROUTER = self._orig_router
        B.fetch_one_company = self._orig_fetch_one
        B.chat_json = self._orig_chat_json
        B.judge_claim = self._orig_judge
        B.llm_config = self._orig_llm_config

    def _claim(self, **kw):
        base = {
            "season": "秋招", "batch": "提前批", "event": "开放",
            "month_start": 7, "month_end": 7, "value_text": "约7月",
            "source_idx": 0, "quote": "提前批7月开放网申",
        }
        base.update(kw)
        return base

    def test_official_grounded_entailment_verified(self):
        # (a) 官方 grounding + 判官 entailment → 自动 verified
        B._ROUTER = _FakeRouter([
            {"title": "校招公告", "url": "https://jobs.testco.com/campus/1",
             "snippet": "提前批7月开放网申", "text": "提前批7月开放网申", "publisher": "testco官网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": [self._claim()]}
        B.judge_claim = lambda content, text, **kw: {"verdict": "entailment", "confidence": 0.9, "reason": "ok"}
        sb = FakeSB(canned={
            "sources": [{"company": "测试公司", "source_url": "https://jobs.testco.com/campus"}],
        })
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["verified"], 1)
        self.assertEqual(stats["draft"], 0)
        rows = sb.inserted.get("recruitment_cycle_observations", [])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["verify_status"], "verified")
        self.assertEqual(row["source_kind"], "official_notice")
        self.assertEqual(row["confidence"], "high")
        self.assertEqual(row["company_id"], "co-1")
        self.assertEqual(row["created_by"], "cron")
        self.assertEqual(row["time_expr_type"], "月")
        self.assertEqual(row["evidence_url"], "https://jobs.testco.com/campus/1")
        self.assertTrue(row["grad_class"].endswith("届"))
        self.assertTrue(row["valid_until"].endswith("-06-30"))

    def test_non_official_entailment_stays_draft(self):
        # (b) 判官 entailment 但非官方源 grounding → 停 draft（宁缺不编，用户读不到）
        B._ROUTER = _FakeRouter([
            {"title": "牛客讨论", "url": "https://www.nowcoder.com/discuss/1",
             "snippet": "提前批7月开放网申", "text": "提前批7月开放网申", "publisher": "牛客网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": [self._claim()]}
        B.judge_claim = lambda content, text, **kw: {"verdict": "entailment", "confidence": 0.9, "reason": "ok"}
        sb = FakeSB(canned={"sources": []})  # 该公司没有任何自有官方源 → 官方 host 集合为空
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["verified"], 0)
        self.assertEqual(stats["draft"], 1)
        rows = sb.inserted.get("recruitment_cycle_observations", [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verify_status"], "draft")
        self.assertEqual(rows[0]["source_kind"], "public_aggregate")

    def test_existing_verified_slot_not_overwritten(self):
        # (c) 该 (届别,季,批次,事件) 已有 verified 行 → 新 claim 直接跳过，绝不覆盖已定案事实
        B._ROUTER = _FakeRouter([
            {"title": "校招公告", "url": "https://jobs.testco.com/campus/1",
             "snippet": "提前批7月开放网申", "text": "提前批7月开放网申", "publisher": "testco官网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": [self._claim()]}
        B.judge_claim = lambda content, text, **kw: {"verdict": "entailment", "confidence": 0.9, "reason": "ok"}
        grad_class, _ = B.current_cohort(datetime.now(timezone.utc))
        sb = FakeSB(canned={
            "sources": [{"company": "测试公司", "source_url": "https://jobs.testco.com/campus"}],
            "recruitment_cycle_observations": [{
                "company_id": "co-1", "grad_class": grad_class,
                "season": "秋招", "batch": "提前批", "event": "开放", "verify_status": "verified",
            }],
        })
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["verified"], 0)
        self.assertEqual(stats["draft"], 0)
        self.assertEqual(stats["skipped_conflict"], 1)
        self.assertEqual(sb.inserted.get("recruitment_cycle_observations", []), [])

    def test_existing_draft_slot_not_duplicated_when_new_also_draft(self):
        # 幂等：已有 draft、新判定也只是 draft → 不重复堆积（不算冲突，算去重）
        B._ROUTER = _FakeRouter([
            {"title": "牛客讨论", "url": "https://www.nowcoder.com/discuss/1",
             "snippet": "提前批7月开放网申", "text": "提前批7月开放网申", "publisher": "牛客网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": [self._claim()]}
        B.judge_claim = lambda content, text, **kw: {"verdict": "entailment", "confidence": 0.9, "reason": "ok"}
        grad_class, _ = B.current_cohort(datetime.now(timezone.utc))
        sb = FakeSB(canned={
            "sources": [],
            "recruitment_cycle_observations": [{
                "company_id": "co-1", "grad_class": grad_class,
                "season": "秋招", "batch": "提前批", "event": "开放", "verify_status": "draft",
            }],
        })
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["skipped_dup_draft"], 1)
        self.assertEqual(sb.inserted.get("recruitment_cycle_observations", []), [])

    def test_no_company_skips(self):
        B.fetch_one_company = lambda sb, company: None
        stats = B.drain_one_company(FakeSB(), "查无公司")
        self.assertEqual(stats["skipped"], "no_company")

    def test_llm_not_configured_skips(self):
        B.llm_config = lambda: {"configured": False}
        stats = B.drain_one_company(FakeSB(), "测试公司")
        self.assertEqual(stats["skipped"], "llm_not_configured")

    def test_budget_exhausted_skips(self):
        B._ROUTER = _FakeRouter([], remaining=0)
        stats = B.drain_one_company(FakeSB(), "测试公司")
        self.assertTrue(stats.get("budget_exhausted"))

    def test_empty_search_results_skips(self):
        B._ROUTER = _FakeRouter([])
        stats = B.drain_one_company(FakeSB(canned={"sources": []}), "测试公司")
        self.assertEqual(stats["skipped"], "no_search_results")

    def test_bad_source_idx_skipped_not_inserted(self):
        B._ROUTER = _FakeRouter([
            {"title": "t", "url": "https://jobs.testco.com/campus/1",
             "snippet": "x", "text": "x", "publisher": "testco官网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": [self._claim(source_idx=5)]}
        B.judge_claim = lambda content, text, **kw: {"verdict": "entailment", "confidence": 0.9, "reason": "ok"}
        sb = FakeSB(canned={"sources": []})
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["skipped_bad_index"], 1)
        self.assertEqual(sb.inserted.get("recruitment_cycle_observations", []), [])

    def test_no_claims_returns_stats_without_insert(self):
        B._ROUTER = _FakeRouter([
            {"title": "t", "url": "https://jobs.testco.com/campus/1",
             "snippet": "x", "text": "x", "publisher": "testco官网"},
        ])
        B.chat_json = lambda messages, **kw: {"claims": []}
        sb = FakeSB(canned={"sources": []})
        stats = B.drain_one_company(sb, "测试公司")
        self.assertEqual(stats["claims_seen"], 0)
        self.assertEqual(sb.inserted.get("recruitment_cycle_observations", []), [])


class CurrentCohortTest(unittest.TestCase):
    def test_july_rolls_to_next_grad_year(self):
        grad_class, valid_until = B.current_cohort(datetime(2026, 7, 15, tzinfo=timezone.utc))
        self.assertEqual(grad_class, "2027届")
        self.assertEqual(valid_until, "2027-06-30")

    def test_march_stays_in_current_grad_year(self):
        grad_class, valid_until = B.current_cohort(datetime(2027, 3, 1, tzinfo=timezone.utc))
        self.assertEqual(grad_class, "2027届")
        self.assertEqual(valid_until, "2027-06-30")

    def test_boundary_month_may_rolls_forward(self):
        grad_class, _ = B.current_cohort(datetime(2026, 5, 1, tzinfo=timezone.utc))
        self.assertEqual(grad_class, "2027届")

    def test_boundary_month_april_stays(self):
        grad_class, _ = B.current_cohort(datetime(2026, 4, 30, tzinfo=timezone.utc))
        self.assertEqual(grad_class, "2026届")


class SelectCycleTargetsTest(unittest.TestCase):
    def test_collapsed_industries_prioritized(self):
        must_apply = {
            "互联网/科技": [{"name": "科技甲", "pattern": "%科技甲%"}],
            "教育": [{"name": "教育乙", "pattern": "%教育乙%"}],
        }
        out = B.select_cycle_targets(must_apply, set(), cap=10, seed=1)
        names = [t["company"] for t in out]
        self.assertEqual(names[0], "教育乙")
        self.assertIn("科技甲", names)

    def test_covered_company_excluded(self):
        must_apply = {"教育": [{"name": "教育乙", "pattern": "%教育乙%"}]}
        out = B.select_cycle_targets(must_apply, {"教育乙"}, cap=10, seed=1)
        self.assertEqual(out, [])

    def test_cap_limits_batch(self):
        must_apply = {"金融": [{"name": f"C{i}", "pattern": f"%C{i}%"} for i in range(20)]}
        out = B.select_cycle_targets(must_apply, set(), cap=5, seed=1)
        self.assertEqual(len(out), 5)

    def test_seed_rotation_deterministic_but_varies(self):
        must_apply = {"金融": [{"name": f"C{i}", "pattern": f"%C{i}%"} for i in range(20)]}
        a = [t["company"] for t in B.select_cycle_targets(must_apply, set(), cap=5, seed=1)]
        a2 = [t["company"] for t in B.select_cycle_targets(must_apply, set(), cap=5, seed=1)]
        b = [t["company"] for t in B.select_cycle_targets(must_apply, set(), cap=5, seed=2)]
        self.assertEqual(a, a2)
        self.assertNotEqual(a, b)

    def test_dedup_across_industries(self):
        # 同名公司若在多个行业清单里重复出现，只挑一次
        must_apply = {
            "教育": [{"name": "重复公司", "pattern": "%重复%"}],
            "金融": [{"name": "重复公司", "pattern": "%重复%"}],
        }
        out = B.select_cycle_targets(must_apply, set(), cap=10, seed=1)
        self.assertEqual(len(out), 1)

    def test_non_dict_entries_and_missing_name_ignored(self):
        must_apply = {"教育": ["not-a-dict", {"pattern": "%x%"}, {"name": "", "pattern": "%y%"}]}
        out = B.select_cycle_targets(must_apply, set(), cap=10, seed=1)
        self.assertEqual(out, [])

    def test_empty_inputs(self):
        self.assertEqual(B.select_cycle_targets({}, set(), cap=10, seed=1), [])
        self.assertEqual(B.select_cycle_targets(None, None, cap=10, seed=1), [])


if __name__ == "__main__":
    unittest.main()
