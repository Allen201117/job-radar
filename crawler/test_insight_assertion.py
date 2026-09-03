"""职业洞察 v3 断言强度写入护栏（纯函数，不打网络或数据库）。"""
import unittest

import insight_backlog as B


class NormalizeAssertionTest(unittest.TestCase):
    def test_public_web_fact_is_downgraded_with_warning(self):
        with self.assertLogs(B.LOG, level="WARNING") as logs:
            actual = B.normalize_assertion("public_web", "fact")
        self.assertEqual(actual, ("claim", "experience"))
        self.assertIn("downgraded", logs.output[0])

    def test_official_filing_is_fact(self):
        self.assertEqual(
            B.normalize_assertion("official_filing", "fact"),
            ("fact", "fact"),
        )

    def test_derived_is_signal(self):
        self.assertEqual(
            B.normalize_assertion("derived", "experience"),
            ("signal", "experience"),
        )

    def test_manual_uses_grade_mapping(self):
        self.assertEqual(B.normalize_assertion("manual", "fact"), ("fact", "fact"))
        self.assertEqual(B.normalize_assertion("manual", "experience"), ("claim", "experience"))

    def test_already_correct_values_are_idempotent(self):
        cases = [
            ("public_web", "experience", ("claim", "experience")),
            ("official", "fact", ("fact", "fact")),
            ("derived", "fact", ("signal", "fact")),
        ]
        for origin, grade, expected in cases:
            with self.subTest(origin=origin, grade=grade):
                self.assertEqual(B.normalize_assertion(origin, grade), expected)


if __name__ == "__main__":
    unittest.main()
