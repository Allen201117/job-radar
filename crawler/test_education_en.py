import unittest

import normalizer


class EducationEnglishVariantsTest(unittest.TestCase):
    def test_extract_education_english_variants(self):
        cases = [
            ("Bachelor's degree required", "本科"),
            ("B.S. in Computer Science", "本科"),
            ("B.A. or equivalent experience", "本科"),
            ("Master's degree", "硕士"),
            ("M.S. or equivalent", "硕士"),
            ("MSc in Statistics", "硕士"),
            ("Ph.D. in Machine Learning", "博士"),
            ("Associate degree", "大专"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(normalizer.extract_education(text), expected)


if __name__ == "__main__":
    unittest.main()
