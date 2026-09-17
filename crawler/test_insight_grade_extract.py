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


class TestAttemptBookkeeping(unittest.TestCase):
    """判不出档必须留痕，否则同一批会被每天重选、永久空烧（2026-09-09~17 实测 9 天）。"""

    def _run(self, rows, dry_run=True, sb=None):
        with patch.object(extract.llm_budget, "check_and_consume", return_value=True), \
             patch.object(extract.insight_engine, "chat_json", return_value={
                 "grades": [{"i": index, "g": None} for index in range(len(rows))],
             }):
            return extract.extract_grades(sb or FakeSupabase(), rows, dry_run=dry_run, max_attempts=3)

    def test_ungraded_rows_bump_attempts_and_graded_rows_do_not(self):
        rows = [
            {"id": "a", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 0},
            {"id": "b", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 1},
        ]
        plan = self._run(rows)
        self.assertEqual(plan["attempt_bumps"], [
            {"id": "a", "grade_attempts": 1},
            {"id": "b", "grade_attempts": 2},
        ])
        self.assertEqual(plan["attempts_exhausted"], 0)
        self.assertEqual(plan["updates"], [])

        with patch.object(extract.llm_budget, "check_and_consume", return_value=True), \
             patch.object(extract.insight_engine, "chat_json", return_value={"grades": [{"i": 0, "g": 3}]}):
            graded = extract.extract_grades(
                FakeSupabase(),
                [{"id": "c", "metric_key": "overtime_level", "content": "有加班", "grade_attempts": 0}],
                dry_run=True,
                max_attempts=3,
            )
        self.assertEqual(graded["attempt_bumps"], [])

    def test_reaching_cap_is_counted_as_exhausted(self):
        rows = [{"id": "a", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 2}]
        plan = self._run(rows)
        self.assertEqual(plan["attempt_bumps"], [{"id": "a", "grade_attempts": 3}])
        self.assertEqual(plan["attempts_exhausted"], 1)

    def test_missing_attempt_column_defaults_to_zero(self):
        plan = self._run([{"id": "a", "metric_key": "overtime_level", "content": "判不出"}])
        self.assertEqual(plan["attempt_bumps"], [{"id": "a", "grade_attempts": 1}])

    def test_apply_writes_attempts_grouped_and_never_touches_metric_value(self):
        sb = FakeSupabase()
        rows = [
            {"id": "a", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 0},
            {"id": "b", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 0},
            {"id": "c", "metric_key": "overtime_level", "content": "判不出", "grade_attempts": 1},
        ]
        self._run(rows, dry_run=False, sb=sb)
        writes = [(entry[1], entry[2]) for entry in sb.log if entry[0] == "update"]
        self.assertEqual(len(writes), 2)
        for values, ids in writes:
            self.assertNotIn("metric_value", values)
            self.assertIn("grade_attempted_at", values)
        by_attempts = {values["grade_attempts"]: ids for values, ids in writes}
        self.assertEqual(by_attempts[1], ["a", "b"])
        self.assertEqual(by_attempts[2], ["c"])

    def test_dry_run_records_nothing(self):
        sb = FakeSupabase()
        self._run([{"id": "a", "metric_key": "overtime_level", "content": "判不出"}], sb=sb)
        self.assertEqual(sb.log, [])

    def test_max_attempts_env_falls_back_on_garbage(self):
        for raw in ("", "0", "-3", "abc", None):
            with patch.dict(extract.os.environ, {} if raw is None else {"GRADE_MAX_ATTEMPTS": raw}, clear=False):
                if raw is None:
                    extract.os.environ.pop("GRADE_MAX_ATTEMPTS", None)
                self.assertEqual(extract.max_grade_attempts(), extract.DEFAULT_MAX_GRADE_ATTEMPTS)
        with patch.dict(extract.os.environ, {"GRADE_MAX_ATTEMPTS": "5"}, clear=False):
            self.assertEqual(extract.max_grade_attempts(), 5)


if __name__ == "__main__":
    unittest.main()
