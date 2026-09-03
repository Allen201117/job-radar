"""档位映射的纯函数契约：离线验证，不接触 LLM 或数据库。"""
import unittest

import insight_grade_scale as grades


class TestGradeScale(unittest.TestCase):
    def test_coerce_grade_accepts_only_integral_grades_one_to_five(self):
        self.assertEqual(grades.coerce_grade("3"), 3)
        self.assertEqual(grades.coerce_grade(3.0), 3)
        for value in (0, 6, "高", None, ""):
            with self.subTest(value=value):
                self.assertIsNone(grades.coerce_grade(value))

    def test_parse_response_pads_missing_positions_without_shifting(self):
        payload = {"grades": [{"i": 1, "g": 4}]}
        self.assertEqual(grades.parse_response(payload, 3), [None, 4, None])

    def test_parse_response_uses_i_to_restore_out_of_order_results(self):
        payload = {
            "grades": [
                {"i": 2, "g": 5},
                {"i": 0, "g": 1},
                {"i": 1, "g": 3},
            ],
        }
        self.assertEqual(grades.parse_response(payload, 3), [1, 3, 5])

    def test_parse_response_returns_all_none_for_dirty_payload(self):
        self.assertEqual(grades.parse_response({"grades": "bad"}, 2), [None, None])

    def test_build_prompt_includes_every_grade_meaning_for_metric(self):
        messages = grades.build_prompt("overtime_level", [{"content": "团队基本双休。"}])
        rendered = "\n".join(message["content"] for message in messages)
        for meaning in grades.GRADE_SCALES["overtime_level"].values():
            self.assertIn(meaning, rendered)

    def test_is_gradable_only_allows_the_three_grade_metrics(self):
        for key in ("overtime_level", "promotion_pace", "intern_experience"):
            with self.subTest(key=key):
                self.assertTrue(grades.is_gradable(key))
        for key in ("bonus_months", "pay_level", "interview_rounds"):
            with self.subTest(key=key):
                self.assertFalse(grades.is_gradable(key))

    def test_build_prompt_handles_empty_items(self):
        messages = grades.build_prompt("intern_experience", [])
        self.assertEqual(len(messages), 2)
        self.assertIn("[]", messages[1]["content"])


if __name__ == "__main__":
    unittest.main()
