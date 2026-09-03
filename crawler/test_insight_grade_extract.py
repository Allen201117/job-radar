"""档位批处理的离线行为：不调 LLM、不连接 Supabase。"""
import unittest
from unittest.mock import patch

import insight_grade_extract as extract


class FakeQuery:
    def __init__(self, log):
        self.log = log
        self.values = None
        self.ids = None

    def upsert(self, payload, **kwargs):
        self.log.append(("upsert", payload, kwargs))
        return self

    def update(self, values):
        self.values = values
        return self

    def in_(self, column, ids):
        self.ids = list(ids)
        return self

    def execute(self):
        self.log.append(("update", self.values, self.ids))
        return self


class FakeSupabase:
    def __init__(self):
        self.log = []

    def table(self, _name):
        return FakeQuery(self.log)


class TestGradeExtraction(unittest.TestCase):
    def test_apply_updates_groups_same_grade_with_update_not_upsert(self):
        sb = FakeSupabase()
        extract.apply_updates(
            sb,
            [
                {"id": "a", "metric_value": 3, "metric_unit": "档"},
                {"id": "b", "metric_value": 3, "metric_unit": "档"},
                {"id": "c", "metric_value": 5, "metric_unit": "档"},
            ],
        )
        self.assertEqual([entry for entry in sb.log if entry[0] == "upsert"], [])
        writes = [(entry[1], entry[2]) for entry in sb.log if entry[0] == "update"]
        self.assertIn(({"metric_value": 3, "metric_unit": "档"}, ["a", "b"]), writes)
        self.assertIn(({"metric_value": 5, "metric_unit": "档"}, ["c"]), writes)

    def test_budget_exhaustion_keeps_completed_batch_and_stops_before_next_call(self):
        rows = [
            {"id": str(i), "metric_key": "overtime_level", "content": f"说法{i}"}
            for i in range(21)
        ]
        with patch.object(extract.llm_budget, "check_and_consume", side_effect=[True, False]) as budget, \
             patch.object(extract.insight_engine, "chat_json", return_value={
                 "grades": [{"i": i, "g": 2} for i in range(20)],
             }) as chat:
            plan = extract.extract_grades(FakeSupabase(), rows, dry_run=True)

        self.assertEqual(budget.call_count, 2)
        self.assertEqual(chat.call_count, 1)
        self.assertTrue(plan["budget_exhausted"])
        self.assertEqual(len(plan["updates"]), 20)
        self.assertEqual(plan["updates"][0], {"id": "0", "metric_value": 2, "metric_unit": "档"})
        self.assertEqual(plan["updates"][-1]["id"], "19")

    def test_dry_run_never_writes_even_when_grades_are_found(self):
        sb = FakeSupabase()
        rows = [{"id": "a", "metric_key": "intern_experience", "content": "有导师带教。"}]
        with patch.object(extract.llm_budget, "check_and_consume", return_value=True), \
             patch.object(extract.insight_engine, "chat_json", return_value={"grades": [{"i": 0, "g": 4}]}):
            plan = extract.extract_grades(sb, rows, dry_run=True)

        self.assertEqual(len(plan["updates"]), 1)
        self.assertEqual(sb.log, [])


if __name__ == "__main__":
    unittest.main()
