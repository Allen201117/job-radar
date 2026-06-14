import unittest

import run


class SummaryBudgetTest(unittest.TestCase):
    def test_job_summary_is_capped_for_storage(self):
        text = "岗位职责：" + ("负责数据平台建设。" * 200)

        capped = run.cap_summary_for_storage(text)

        self.assertLessEqual(len(capped), run.SUMMARY_STORAGE_LIMIT)
        self.assertTrue(capped.endswith("..."))

    def test_empty_summary_stays_none(self):
        self.assertIsNone(run.cap_summary_for_storage(None))
        self.assertIsNone(run.cap_summary_for_storage(""))
        self.assertIsNone(run.cap_summary_for_storage("   "))


if __name__ == "__main__":
    unittest.main()
