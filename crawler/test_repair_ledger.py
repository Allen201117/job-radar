"""repair_ledger 契约：枚举校验、ask 必填、截断、空 items 合法、counts 全键、status 映射。
单测不连库。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import repair_ledger as rl  # noqa: E402


def item(**over):
    base = {"check_id": "jobs.active_total", "title": "标题", "outcome": "fixed", "evidence": "证据"}
    base.update(over)
    return base


class ValidateItemsTests(unittest.TestCase):
    def test_valid_item_passes(self):
        cleaned = rl.validate_items([item()])
        self.assertEqual(cleaned[0]["outcome"], "fixed")

    def test_unknown_outcome_rejected(self):
        with self.assertRaises(ValueError):
            rl.validate_items([item(outcome="not_a_real_outcome")])

    def test_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            rl.validate_items([item(title="  ")])

    def test_empty_evidence_rejected(self):
        with self.assertRaises(ValueError):
            rl.validate_items([item(evidence="")])

    def test_waiting_founder_requires_ask(self):
        with self.assertRaises(ValueError):
            rl.validate_items([item(outcome="waiting_founder")])
        cleaned = rl.validate_items([item(outcome="waiting_founder", ask="请拍板")])
        self.assertEqual(cleaned[0]["ask"], "请拍板")

    def test_needs_founder_action_requires_ask(self):
        with self.assertRaises(ValueError):
            rl.validate_items([item(outcome="needs_founder_action")])

    def test_fixed_outcome_does_not_require_ask(self):
        cleaned = rl.validate_items([item(outcome="fixed")])
        self.assertIsNone(cleaned[0]["ask"])

    def test_missing_check_id_and_issue_rejected(self):
        bad = {"title": "t", "outcome": "fixed", "evidence": "e"}
        with self.assertRaises(ValueError):
            rl.validate_items([bad])

    def test_issue_field_accepted_in_place_of_check_id(self):
        row = {"issue": "42", "title": "t", "outcome": "fixed", "evidence": "e"}
        cleaned = rl.validate_items([row])
        self.assertEqual(cleaned[0]["issue"], "42")

    def test_long_fields_truncated(self):
        cleaned = rl.validate_items([item(title="x" * 300, evidence="y" * 300)])
        self.assertLessEqual(len(cleaned[0]["title"]), 200)
        self.assertTrue(cleaned[0]["title"].endswith("…"))
        self.assertLessEqual(len(cleaned[0]["evidence"]), 200)

    def test_empty_items_list_is_valid(self):
        self.assertEqual(rl.validate_items([]), [])

    def test_items_not_a_list_rejected(self):
        with self.assertRaises(ValueError):
            rl.validate_items({"not": "a list"})


class BuildMetricsTests(unittest.TestCase):
    def test_all_outcome_keys_present_even_zero(self):
        metrics = rl.build_metrics([])
        for outcome in rl.OUTCOMES:
            self.assertIn(outcome, metrics["counts"])
            self.assertEqual(metrics["counts"][outcome], 0)
        self.assertEqual(metrics["total"], 0)
        self.assertEqual(metrics["items"], [])

    def test_counts_tally_correctly(self):
        items = rl.validate_items([item(outcome="fixed"), item(outcome="fixed"),
                                    item(outcome="closed_stale")])
        metrics = rl.build_metrics(items)
        self.assertEqual(metrics["counts"]["fixed"], 2)
        self.assertEqual(metrics["counts"]["closed_stale"], 1)
        self.assertEqual(metrics["total"], 3)


class StatusForTests(unittest.TestCase):
    def test_fix_failed_makes_partial(self):
        items = rl.validate_items([item(outcome="fix_failed")])
        self.assertEqual(rl.status_for(items), "partial")

    def test_no_fix_failed_is_success(self):
        items = rl.validate_items([item(outcome="fixed"), item(outcome="still_breaching")])
        self.assertEqual(rl.status_for(items), "success")

    def test_empty_items_is_success(self):
        self.assertEqual(rl.status_for([]), "success")


class MainTests(unittest.TestCase):
    def _write_payload(self, payload):
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, fh)
        fh.close()
        return fh.name

    def test_invalid_payload_exits_nonzero_without_writing(self):
        path = self._write_payload({"items": [{"outcome": "bogus", "title": "t", "evidence": "e",
                                                  "check_id": "a"}]})
        try:
            with mock.patch("repair_ledger.db") as _:
                code = rl.main(["--file", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 1)

    def test_empty_items_writes_heartbeat_row(self):
        path = self._write_payload({"items": []})
        recorded = {}

        def fake_record(sb, module, metrics, status=None, started_at=None, finished_at=None):
            recorded.update(module=module, metrics=metrics, status=status)
            return True

        try:
            with mock.patch.object(rl, "db") as fake_db, \
                 mock.patch.object(rl.ops_runs, "record_ops_run", side_effect=fake_record):
                fake_db.get_supabase.return_value = object()
                code = rl.main(["--file", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 0)
        self.assertEqual(recorded["module"], "auto_repair")
        self.assertEqual(recorded["metrics"]["total"], 0)
        self.assertEqual(recorded["status"], "success")

    def test_record_ops_run_failure_exits_nonzero(self):
        path = self._write_payload({"items": [item()]})
        try:
            with mock.patch.object(rl, "db") as fake_db, \
                 mock.patch.object(rl.ops_runs, "record_ops_run", return_value=False):
                fake_db.get_supabase.return_value = object()
                code = rl.main(["--file", path])
        finally:
            os.unlink(path)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
