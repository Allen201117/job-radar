import unittest

import normalizer


class JobTypeEnglishSignalsTest(unittest.TestCase):
    def test_extract_job_type_english_launch_signals(self):
        cases = [
            ("Software Engineer Intern", None, "实习"),
            ("Summer 2026 Internship", None, "暑期实习"),
            ("New Grad Software Engineer", None, "校招"),
            ("University Graduate - Engineering", None, "校招"),
            ("Entry Level Data Analyst", None, "校招"),
            ("Senior Software Engineer", None, "社招"),
            ("Staff Engineer", None, "社招"),
        ]
        for title, summary, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(normalizer.extract_job_type(title, summary), expected)

    def test_graduate_degree_remains_education_not_campus(self):
        self.assertIsNone(
            normalizer.extract_job_type("Data Scientist", "Graduate degree in CS or related field.")
        )


if __name__ == "__main__":
    unittest.main()
