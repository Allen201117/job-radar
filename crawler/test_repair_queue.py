"""repair_queue 契约：排序、info 过滤、缺行→没查到、prior_attempts/give_up、连库失败非零退出。
单测不连库。
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import repair_queue as rq  # noqa: E402
import morning_digest as md  # noqa: E402


def check(cid, layer="data", severity="warn", source="sql", **over):
    base = {
        "id": cid, "name": f"人话-{cid}", "layer": layer, "severity": severity,
        "why": "为什么", "action": "怎么办", "owner": "owner", "normal": ">= 0",
        "source": source,
    }
    base.update(over)
    return base


def result_row(cid, value, verdict, severity="warn", detail=None):
    return {
        "check_id": cid, "layer": "data", "severity": severity, "value": value,
        "normal": ">= 0", "verdict": verdict, "calibrated": True,
        "error_message": None, "detail": detail,
    }


class BuildRepairQueueTests(unittest.TestCase):
    def test_ok_rows_excluded(self):
        checks = [check("a")]
        results = {"a": result_row("a", 1, "ok")}
        self.assertEqual(rq.build_repair_queue(checks, results), [])

    def test_info_severity_excluded_even_if_breach(self):
        checks = [check("a", severity="info")]
        results = {"a": result_row("a", 1, "breach", severity="info")}
        self.assertEqual(rq.build_repair_queue(checks, results), [])

    def test_missing_row_composes_via_merge_missing_as_error(self):
        checks = [check("a", severity="critical")]
        merged = md.merge_missing_as_error(checks, {})
        items = rq.build_repair_queue(checks, merged)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["verdict"], "error")
        self.assertEqual(items[0]["value"], None)

    def test_fields_come_from_contract_not_stale_row(self):
        checks = [check("a", name="最新人话名", why="最新why", action="最新action", owner="最新owner")]
        results = {"a": result_row("a", 5, "breach")}
        items = rq.build_repair_queue(checks, results)
        self.assertEqual(items[0]["name"], "最新人话名")
        self.assertEqual(items[0]["why"], "最新why")
        self.assertEqual(items[0]["action"], "最新action")
        self.assertEqual(items[0]["owner"], "最新owner")
        self.assertEqual(items[0]["value"], 5)

    def test_findings_pulled_from_detail(self):
        checks = [check("watchdog.rule_a", source="watchdog")]
        results = {"watchdog.rule_a": result_row(
            "watchdog.rule_a", 3, "breach", detail={"findings": [{"title": "t", "key": "k"}]}
        )}
        items = rq.build_repair_queue(checks, results)
        self.assertEqual(items[0]["findings"], [{"title": "t", "key": "k"}])

    def test_findings_absent_when_no_detail(self):
        checks = [check("a")]
        results = {"a": result_row("a", 5, "breach")}
        items = rq.build_repair_queue(checks, results)
        self.assertIsNone(items[0]["findings"])

    def test_sort_critical_before_warn(self):
        checks = [check("w", severity="warn"), check("c", severity="critical")]
        results = {
            "w": result_row("w", 1, "breach", severity="warn"),
            "c": result_row("c", 1, "breach", severity="critical"),
        }
        items = rq.build_repair_queue(checks, results)
        self.assertEqual([i["check_id"] for i in items], ["c", "w"])

    def test_sort_error_before_breach_within_same_severity(self):
        checks = [check("b", severity="warn"), check("e", severity="warn")]
        results = {
            "b": result_row("b", 1, "breach", severity="warn"),
            "e": result_row("e", None, "error", severity="warn"),
        }
        items = rq.build_repair_queue(checks, results)
        self.assertEqual([i["check_id"] for i in items], ["e", "b"])

    def test_sort_by_layer_data_then_pipeline_then_experience(self):
        checks = [
            check("exp1", layer="experience", severity="warn"),
            check("pipe1", layer="pipeline", severity="warn"),
            check("data1", layer="data", severity="warn"),
        ]
        results = {cid: result_row(cid, 1, "breach", severity="warn") for cid in
                   ("exp1", "pipe1", "data1")}
        items = rq.build_repair_queue(checks, results)
        self.assertEqual([i["check_id"] for i in items], ["data1", "pipe1", "exp1"])

    def test_give_up_boundary(self):
        checks = [check("a", severity="warn")]
        results = {"a": result_row("a", 1, "breach", severity="warn")}
        one = rq.build_repair_queue(checks, results, {"a": 1})
        self.assertFalse(one[0]["give_up"])
        two = rq.build_repair_queue(checks, results, {"a": 2})
        self.assertTrue(two[0]["give_up"])
        self.assertEqual(two[0]["prior_attempts"], 2)


class CountPriorAttemptsTests(unittest.TestCase):
    def test_counts_fix_failed_and_still_breaching_with_commit(self):
        rows = [
            {"metrics": {"items": [{"check_id": "a", "outcome": "fix_failed"}]}},
            {"metrics": {"items": [{"check_id": "a", "outcome": "still_breaching", "commit": "abc1234"}]}},
        ]
        self.assertEqual(rq.count_prior_attempts(rows), {"a": 2})

    def test_still_breaching_without_commit_not_counted(self):
        """兼容 2026-09-19 首次运行落库的历史行：那批 still_breaching 没有 commit，
        代表『今天没排到/只诊断』而不是『真动手修过没修好』，不许计入 give_up。"""
        rows = [{"metrics": {"items": [{"check_id": "a", "outcome": "still_breaching"}]}}]
        self.assertEqual(rq.count_prior_attempts(rows), {})

    def test_deferred_outcome_not_counted(self):
        rows = [{"metrics": {"items": [{"check_id": "a", "outcome": "deferred"}]}}]
        self.assertEqual(rq.count_prior_attempts(rows), {})

    def test_fixed_outcome_not_counted(self):
        rows = [{"metrics": {"items": [{"check_id": "a", "outcome": "fixed"}]}}]
        self.assertEqual(rq.count_prior_attempts(rows), {})

    def test_falls_back_to_issue_key(self):
        rows = [{"metrics": {"items": [{"issue": "42", "outcome": "fix_failed"}]}}]
        self.assertEqual(rq.count_prior_attempts(rows), {"42": 1})

    def test_empty_rows(self):
        self.assertEqual(rq.count_prior_attempts([]), {})
        self.assertEqual(rq.count_prior_attempts(None), {})

    def test_non_dict_items_ignored(self):
        rows = [{"metrics": {"items": ["not-a-dict"]}}]
        self.assertEqual(rq.count_prior_attempts(rows), {})

    def test_two_real_failures_trigger_give_up(self):
        """两次『真动手修了但没修好』（fix_failed + 带 commit 的 still_breaching）才 give_up。"""
        rows = [
            {"metrics": {"items": [{"check_id": "a", "outcome": "fix_failed"}]}},
            {"metrics": {"items": [{"check_id": "a", "outcome": "still_breaching", "commit": "def5678"}]}},
        ]
        prior = rq.count_prior_attempts(rows)
        checks = [check("a", severity="warn")]
        results = {"a": result_row("a", 1, "breach", severity="warn")}
        items = rq.build_repair_queue(checks, results, prior)
        self.assertTrue(items[0]["give_up"])


class MainConnectFailureTests(unittest.TestCase):
    def test_connect_failure_exits_nonzero_and_prints_no_empty_array(self):
        buf = io.StringIO()
        with mock.patch.object(rq._audit_runner, "load_contract", return_value=[]), \
             mock.patch.object(rq._audit_runner, "connect", side_effect=RuntimeError("boom")), \
             redirect_stdout(buf):
            code = rq.main(["--json"])
        self.assertEqual(code, 1)
        self.assertNotIn("[]", buf.getvalue())
        self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
