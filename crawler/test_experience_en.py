import unittest

import normalizer


class ExperienceEnglishSeniorityTest(unittest.TestCase):
    def test_seniority_words_fallback_to_years(self):
        cases = [
            ("Entry Level Analyst", "应届/不限"),
            ("Junior Software Engineer", "应届/不限"),
            ("Mid-Level Data Analyst", "3年+"),
            ("Senior Software Engineer", "5年+"),
            ("Staff Engineer", "8年+"),
            ("Lead Engineer", "8年+"),
            ("Principal Engineer", "12年+"),
            ("Distinguished Engineer", "12年+"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalizer.extract_experience(text), expected)

    def test_explicit_numeric_years_take_priority(self):
        self.assertEqual(normalizer.extract_experience("Senior Software Engineer, 3+ years"), "3年+")
        self.assertEqual(normalizer.extract_experience("Principal Engineer, 5 years experience"), "5年+")


if __name__ == "__main__":
    unittest.main()
