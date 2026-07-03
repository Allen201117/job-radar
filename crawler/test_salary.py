"""salary.py 纯函数单测（不打网络）。重点覆盖真库里的噪音必须被拒。"""
import unittest

from salary import extract_salary_text, salary_from_ashby


class TestExtractSalaryText(unittest.TestCase):
    def test_labeled_range(self):
        self.assertEqual(
            extract_salary_text("The salary range for this position is $120,000 - $180,000 per year."),
            "$120,000 – $180,000",
        )

    def test_base_pay_range_k(self):
        self.assertEqual(
            extract_salary_text("Base pay range: $120K–$180K plus equity"),
            "$120K – $180K",
        )

    def test_to_separator(self):
        self.assertEqual(
            extract_salary_text("Expected salary of $95,000 to $130,000 annually"),
            "$95,000 – $130,000",
        )

    # —— 真库噪音，必须拒 ——
    def test_sign_on_bonus_rejected(self):
        self.assertIsNone(extract_salary_text("Job Description $2500 Sign On Bonus Available!"))

    def test_company_revenue_rejected(self):
        self.assertIsNone(extract_salary_text("customers with annual company revenues of $500,000 to $4 million"))

    def test_bonus_range_rejected(self):
        self.assertIsNone(extract_salary_text("****$7,500 bonus provided with internal offer***"))

    def test_tiny_amount_rejected(self):
        self.assertIsNone(extract_salary_text("pay range of $5 to $20 gift card"))

    def test_no_salary_none(self):
        self.assertIsNone(extract_salary_text("We are hiring a backend engineer to build systems."))
        self.assertIsNone(extract_salary_text(""))
        self.assertIsNone(extract_salary_text(None))


class TestSalaryFromAshby(unittest.TestCase):
    def test_tier_summary(self):
        self.assertEqual(
            salary_from_ashby({"compensationTierSummary": "$185K – $325K • Offers Equity"}),
            "$185K – $325K • Offers Equity",
        )

    def test_summary_components_fallback(self):
        comp = {"summaryComponents": [{"compensationType": "Salary", "label": "$150K – $200K"}]}
        self.assertEqual(salary_from_ashby(comp), "$150K – $200K")

    def test_none_when_empty(self):
        self.assertIsNone(salary_from_ashby({}))
        self.assertIsNone(salary_from_ashby(None))
        self.assertIsNone(salary_from_ashby({"compensationTierSummary": "Not disclosed"}))


if __name__ == "__main__":
    unittest.main()
