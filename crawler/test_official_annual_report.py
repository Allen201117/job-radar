"""巨潮年报员工/薪酬解析单测：所有数据均为固定文本 fixture，不打真实网络。"""
import unittest
from unittest import mock

import official_annual_report as A


CATL_EMPLOYEE_TEXT = """\
在职员工的数量合计 131,988
专业构成类别 专业构成人数（人）
生产人员 96,725
技术人员 20,346
行政人员 11,419
销售人员 2,806
财务人员 692
教育程度类别 教育程度人数（人）
博士 625
硕士 8,015
本科 26,292
大专及以下 97,056
"""

CATL_COMPENSATION_TEXT = """\
应付职工薪酬
单位：千元人民币
项目 期初余额 本期增加 本期减少 期末余额
一、短期薪酬（合计） 14,840,448 28,151,691 24,345,435 18,646,704
"""


class _Response:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, payload):
        self.payload = payload
        self.get_calls = []
        self.post_calls = []

    def get(self, *args, **kwargs):
        self.get_calls.append((args, kwargs))
        return _Response()

    def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return _Response(self.payload)


class EmployeeFieldTest(unittest.TestCase):
    def test_catl_fixture_extracts_each_employee_number(self):
        fields = A.extract_employee_fields(CATL_EMPLOYEE_TEXT)
        self.assertEqual(fields["employee_total"], 131988)
        self.assertEqual(fields["emp_production"], 96725)
        self.assertEqual(fields["emp_sales"], 2806)
        self.assertEqual(fields["emp_technical"], 20346)
        self.assertEqual(fields["emp_finance"], 692)
        self.assertEqual(fields["emp_admin"], 11419)
        self.assertEqual(fields["edu_phd"], 625)
        self.assertEqual(fields["edu_master"], 8015)
        self.assertEqual(fields["edu_bachelor"], 26292)
        self.assertEqual(fields["edu_below_bachelor"], 97056)

    def test_education_aliases_are_tolerated(self):
        fields = A.extract_employee_fields("博士 1\n硕士 2\n本科 3\n本科以下 4")
        self.assertEqual(fields["edu_below_bachelor"], 4)
        self.assertEqual(fields["edu_bachelor"], 3)
        self.assertEqual(A.extract_employee_fields("专科 7")["edu_below_bachelor"], 7)


class CompensationAndMetricTest(unittest.TestCase):
    def test_catl_compensation_k_cny_is_converted_to_cny(self):
        fields = A.extract_compensation_fields(CATL_COMPENSATION_TEXT, CATL_COMPENSATION_TEXT)
        self.assertEqual(fields["compensation_current_year_added_reported"], 28151691)
        self.assertEqual(fields["compensation_current_year_added_cny"], 28151691000)

    def test_yuan_unit_and_short_term_employee_salary_alias(self):
        text = "单位：元\n短期职工薪酬 10 20 30 40"
        self.assertEqual(A.extract_compensation_fields(text, text)["compensation_current_year_added_cny"], 20)

    def test_metrics_and_missing_denominator(self):
        fields = A.extract_employee_fields(CATL_EMPLOYEE_TEXT)
        fields.update(A.extract_compensation_fields(CATL_COMPENSATION_TEXT, CATL_COMPENSATION_TEXT))
        metrics = A.derive_metrics(fields)
        self.assertEqual(metrics["technical_ratio"], 0.1542)
        self.assertEqual(metrics["bachelor_or_above_ratio"], 0.2647)
        self.assertEqual(metrics["master_or_above_ratio"], 0.0655)
        self.assertEqual(metrics["avg_compensation_cny_approx"], 213000)
        self.assertNotIn("avg_compensation_cny_approx", A.derive_metrics({"employee_total": 49, "compensation_current_year_added_cny": 100000}))
        self.assertNotIn("avg_compensation_cny_approx", A.derive_metrics({"employee_total": 100}))


class FactItemTest(unittest.TestCase):
    def test_builds_two_items_with_required_disclaimer(self):
        fields = A.extract_employee_fields(CATL_EMPLOYEE_TEXT)
        fields.update(A.extract_compensation_fields(CATL_COMPENSATION_TEXT, CATL_COMPENSATION_TEXT))
        fields["employee_excerpt"] = "在职员工的数量合计 131,988 技术人员 20,346"
        fields["compensation_excerpt"] = "单位：千元人民币 短期薪酬 14,840,448 28,151,691"
        report = {"year": 2024, "adjunct_url": "finalpage/2025-03-15/1222806982.PDF"}
        items = A.build_fact_items({"id": "company-1"}, report, fields, A.derive_metrics(fields))
        self.assertEqual([item["dimension"] for item in items], ["hiring", "compensation_intensity"])
        self.assertIn("在职员工 131,988 人", items[0]["content"])
        self.assertIn("技术人员占 15%", items[0]["content"])
        self.assertEqual(items[0]["origin"], "official_filing")
        self.assertIn("含公司承担的社保公积金，为会计计提口径，仅供量级参考", items[1]["content"])
        self.assertEqual(items[1]["payload"]["report_year"], 2024)
        self.assertEqual(items[1]["source"]["publisher"], "巨潮资讯网")


class AnnouncementAndIdempotencyTest(unittest.TestCase):
    def test_filters_summary_english_wrong_security_code_and_keeps_annual_report(self):
        client = _Client({"announcements": [
            {"secCode": "300750", "announcementTitle": "2024年年度报告", "adjunctUrl": "a.PDF", "announcementTime": 1741996800000},
            {"secCode": "300750", "announcementTitle": "2024年年度报告摘要", "adjunctUrl": "summary.PDF"},
            {"secCode": "300750", "announcementTitle": "2024年年度报告（英文版）", "adjunctUrl": "en.PDF"},
            {"secCode": "000001", "announcementTitle": "2025年年度报告", "adjunctUrl": "wrong.PDF"},
            {"secCode": "300750", "announcementTitle": "2025年年度报告", "adjunctUrl": "new.PDF"},
        ]})
        reports = A.list_annual_reports(client, "宁德时代", "300750")
        self.assertEqual([report["year"] for report in reports], [2025, 2024])
        self.assertEqual(reports[1]["publish_date"], "2025-03-15")
        self.assertEqual(client.post_calls[0][1]["data"]["searchkey"], "宁德时代年度报告")
        self.assertNotIn("seDate", client.post_calls[0][1]["data"])
        self.assertEqual(client.post_calls[0][1]["headers"]["X-Requested-With"], "XMLHttpRequest")

    def test_latest_existing_year_skips_download(self):
        reports = [{"year": 2025, "adjunct_url": "new.PDF"}, {"year": 2024, "adjunct_url": "old.PDF"}]
        self.assertIsNone(A.choose_latest_unseen_report(reports, {2025}))
        self.assertEqual(A.choose_latest_unseen_report(reports, {2024})["year"], 2025)

    def test_existing_latest_year_skips_before_pdf_download(self):
        with mock.patch.object(A, "list_annual_reports", return_value=[{"year": 2025, "adjunct_url": "new.PDF"}]), \
                mock.patch.object(A, "existing_report_years", return_value={2025}), \
                mock.patch.object(A, "download_pdf", side_effect=AssertionError("不应下载已入库年报")):
            result, written = A.process_company(
                object(), object(), {"id": "company-1"}, {"zwjc": "宁德时代", "code": "300750"},
            )
        self.assertEqual((result, written), ("already_latest", 0))


if __name__ == "__main__":
    unittest.main()


class UnitSuffixTest(unittest.TestCase):
    def test_total_with_unit_parenthesis_is_extracted(self):
        # 2025 年报格式：标签后带「（人）」单位括注（live 踩坑：原正则抽不到 → 整家判成无章节）。
        text = "报告期末在职员工的数量合计（人） 185,839\n生产人员 145,568\n博士 818\n硕士 9,000\n本科 30,000\n大专及以下 146,021"
        fields = A.extract_employee_fields(text)
        self.assertEqual(fields["employee_total"], 185839)
        self.assertEqual(fields["edu_master"], 9000)
        self.assertEqual(fields["edu_bachelor"], 30000)

