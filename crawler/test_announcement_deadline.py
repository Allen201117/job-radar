import unittest
from datetime import date

from announcements.deadline import extract_deadline, extract_published, _add_business_days


class TestDeadlineExtraction(unittest.TestCase):
    def test_range_end_full_date(self):
        # Phase 0 实测原文
        d, ev = extract_deadline("报名时间：公告发布之日至2026年9月23日17:00")
        self.assertEqual(d, date(2026, 9, 23))
        self.assertIn("2026", ev)

    def test_deadline_keyword(self):
        d, _ = extract_deadline("报名截止时间：2026年9月22日")
        self.assertEqual(d, date(2026, 9, 22))

    def test_range_with_start_and_end(self):
        d, _ = extract_deadline("报名时间为2026年9月1日9:00至2026年9月30日18:00")
        self.assertEqual(d, date(2026, 9, 30))  # 取区间右端（截止），不是起始

    def test_jieszhi_wei(self):
        d, _ = extract_deadline("报名截止时间为2026年9月27日")
        self.assertEqual(d, date(2026, 9, 27))

    def test_month_day_only_infers_year_from_published(self):
        d, _ = extract_deadline("报名时间自9月1日至9月28日", published_at=date(2026, 9, 1))
        self.assertEqual(d, date(2026, 9, 28))

    def test_business_days_needs_published(self):
        # 无发布日 → 抽不成 date，但带回原文兜底
        d, ev = extract_deadline("自公告发布之日起7个工作日内报名")
        self.assertIsNone(d)
        self.assertIn("工作日", ev)
        # 有发布日 → 算出结构化 date
        d2, _ = extract_deadline("自公告发布之日起7个工作日内报名", published_at=date(2026, 9, 10))
        self.assertEqual(d2, date(2026, 9, 21))  # 周四起第7个工作日

    def test_no_deadline(self):
        d, ev = extract_deadline("本公告由XX单位负责解释。")
        self.assertIsNone(d)
        self.assertIsNone(ev)

    def test_invalid_date_not_crash(self):
        d, _ = extract_deadline("报名截止2026年13月40日")  # 月/日越界
        self.assertIsNone(d)

    def test_fullwidth_digits(self):
        d, _ = extract_deadline("报名截止时间：２０２６年９月２２日")
        self.assertEqual(d, date(2026, 9, 22))

    def test_add_business_days(self):
        self.assertEqual(_add_business_days(date(2026, 9, 10), 1), date(2026, 9, 11))  # Thu→Fri
        self.assertEqual(_add_business_days(date(2026, 9, 11), 1), date(2026, 9, 14))  # Fri→Mon


class TestPublishedExtraction(unittest.TestCase):
    def test_published_cn(self):
        self.assertEqual(extract_published("发布日期：2026年9月14日"), date(2026, 9, 14))

    def test_published_dash(self):
        self.assertEqual(extract_published("发布时间：2026-09-14 来源：XX"), date(2026, 9, 14))

    def test_published_none(self):
        self.assertIsNone(extract_published("来源：某某单位"))


if __name__ == "__main__":
    unittest.main()
