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


    def test_intern_title_beats_campus_signals_in_body(self):
        """标题写着实习生，就不能被正文里的「应届 / 留学生 / 管培」抢走。

        病灶（2026-09-02 全量重算时发现）：校招 / 留学生专项 / 管培生 三条规则都看
        「标题 + 整段正文」且排在实习之前，而实习岗的 JD 正文常写「面向 2027 届应届生」
        「留学生亦可投递」→ `研发实习生@文远知行` 被标成校招、`运维实习生` 被标成留学生专项，
        实习用户在实习专区里根本收不到这些岗。
        """
        cases = [
            ("研发实习生", "面向2027届应届生，校招提前批可转正。", "实习"),
            ("运维实习生", "留学生亦可投递，海外学生优先。", "实习"),
            ("TeleAI-HR人力资源部实习生", "本次校园招聘面向应届毕业生。", "实习"),
            ("财富顾问岗实习生（深圳）", "管理培训生培养体系，应届生优先。", "实习"),
            ("Research Intern - NLP", "Open to new grad and university graduate students.", "实习"),
        ]
        for title, summary, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(normalizer.extract_job_type(title, summary), expected)

    def test_campus_body_signals_still_work_without_intern_title(self):
        """反向：标题不是实习岗时，正文里的「实习经历」不能把它拽成实习。"""
        # 前两条有明确的招聘类型标记，必须判对；第三条判不出（None）是可接受的正确答案——
        # 契约是「正文的实习经历不能把它拽进实习桶」，而不是「必须判成社招」。
        self.assertEqual(normalizer.extract_job_type("2027校园招聘-产品经理", "有相关实习经历者优先。"), "校招")
        self.assertEqual(normalizer.extract_job_type("管理培训生", "需有实习经历，graduate program。"), "管培生")
        for title, summary in [
            ("高级后端工程师", "有大厂实习经历者优先考虑。"),
            ("Senior Data Scientist", "Prior internship experience is a plus."),
            ("产品总监", "曾有实习带教经验者优先。"),
        ]:
            with self.subTest(title=title):
                self.assertNotIn(
                    normalizer.extract_job_type(title, summary),
                    ("实习", "暑期实习", "日常实习"),
                )

    def test_graduate_degree_remains_education_not_campus(self):
        self.assertIsNone(
            normalizer.extract_job_type("Data Scientist", "Graduate degree in CS or related field.")
        )


if __name__ == "__main__":
    unittest.main()
