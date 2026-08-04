import unittest

from grad_class import extract_grad_class


class TestExtractGradClass(unittest.TestCase):
    """与 tests/grad-class.test.js 同口径——两份实现必须给出一致结果，改规则两边同步。"""

    def test_four_digit_year_with_jie(self):
        self.assertEqual(extract_grad_class(title="2027届校园招聘-后端工程师"), 2027)
        self.assertEqual(extract_grad_class(title="2027 届 算法工程师"), 2027)
        self.assertEqual(extract_grad_class(summary="面向2026届毕业生"), 2026)

    def test_two_digit_year_with_jie(self):
        self.assertEqual(extract_grad_class(title="27届秋招-数据分析"), 2027)
        self.assertEqual(extract_grad_class(title="26届春季校园招聘"), 2026)

    def test_year_with_campus_context(self):
        self.assertEqual(extract_grad_class(title="2027校招-产品经理"), 2027)
        self.assertEqual(extract_grad_class(title="2027秋招正式批 前端"), 2027)
        self.assertEqual(extract_grad_class(title="2028春招提前批"), 2028)
        self.assertEqual(extract_grad_class(summary="2027年校园招聘正式启动"), 2027)

    def test_english_signals(self):
        self.assertEqual(extract_grad_class(title="Software Engineer, Class of 2027"), 2027)
        self.assertEqual(extract_grad_class(title="2027 Graduate Program - Analyst"), 2027)

    def test_multiple_takes_max(self):
        self.assertEqual(extract_grad_class(title="2026/2027届校园招聘"), 2027)
        self.assertEqual(
            extract_grad_class(title="26届、27届均可投递", summary="2025届不再接收"), 2027)

    def test_no_hard_signal_returns_none(self):
        # 宁缺不编：不靠入库时间/上下文猜届别
        self.assertIsNone(extract_grad_class(title="校园招聘-后端工程师"))
        self.assertIsNone(extract_grad_class(title="管培生"))
        self.assertIsNone(extract_grad_class())

    def test_bare_year_is_not_grad_class(self):
        self.assertIsNone(extract_grad_class(summary="预计2027年12月前完成入职"))
        self.assertIsNone(extract_grad_class(title="2027 年度预算分析师"))
        self.assertIsNone(extract_grad_class(summary="月薪 20000-27000"))

    def test_year_window_guard(self):
        self.assertIsNone(extract_grad_class(title="1998届校园招聘"))
        self.assertIsNone(extract_grad_class(title="3027届校园招聘"))

    def test_job_type_field_is_also_scanned(self):
        # 不少源把「2027届校园招聘」放在 job_type 而非 title
        self.assertEqual(extract_grad_class(title="后端工程师", job_type="2027届校园招聘"), 2027)


if __name__ == "__main__":
    unittest.main()
