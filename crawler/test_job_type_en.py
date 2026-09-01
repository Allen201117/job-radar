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


    def test_intern_requires_word_boundary(self):
        """internal / international / internet 不是实习。

        真实库实测（2026-09-02）：裸子串 `"intern" in text` 让 27,824 个在招岗被标成实习，
        其中 Stripe 的 "internal tools"、汇丰的 "international banking"、辉瑞的
        "international clinical trials" 全部中招——`Principal Product Manager`（要 6 年经验）
        被标 job_type=实习，会直接推给实习生。
        上面两条 summer/daily intern 规则本来就用了 \b，唯独这条漏了。
        """
        # 契约是「绝不能判成实习」——判不出（None）是可接受的正确答案，
        # 判不出会让下游 recruitmentCategory 继续按 url / 正文 / 经验年限逐层判，
        # 而错标实习会被「实习自报最权威」那层直接锁死。
        cases = [
            ("Staff Software Engineer", "Build internal tools for the platform team."),
            ("Senior Manager, Marketing", "Lead international expansion across ASEAN."),
            ("Principal Product Manager", "Own our internet infrastructure roadmap."),
            ("Communications Director", "Partner with internal stakeholders."),
            ("Data Engineer", "Work on internet-scale distributed systems."),
        ]
        for title, summary in cases:
            with self.subTest(title=title):
                self.assertNotIn(
                    normalizer.extract_job_type(title, summary),
                    ("实习", "暑期实习", "日常实习"),
                )

    def test_real_intern_still_detected(self):
        """收紧不能误伤真实习岗。"""
        cases = [
            ("Software Engineer Intern", None, "实习"),
            ("Marketing Interns (Summer)", None, "实习"),
            ("Data Analyst Internship", None, "实习"),
            ("产品实习生", None, "实习"),
            ("Research Intern - NLP", "Open to current students.", "实习"),
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
