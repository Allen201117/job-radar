import unittest

import company_industry as ci
import discovery


class ClassifyCompanyIndustryTest(unittest.TestCase):
    def test_overrides_and_keywords(self):
        # 与 JS lib/company-industry.js 同口径（共享 JSON）。
        self.assertEqual(ci.classify_company_industry("农夫山泉 养生堂"), "消费/零售")
        self.assertEqual(ci.classify_company_industry("字节跳动"), "互联网/科技")
        self.assertEqual(ci.classify_company_industry("某某制药股份"), "医疗/医药")
        self.assertEqual(ci.classify_company_industry("某某证券"), "金融")

    def test_substring_traps_avoided(self):
        # 子串陷阱：正大集团≠正大天晴药业、TCL中环→能源 先于 TCL→制造。
        self.assertEqual(ci.classify_company_industry("正大天晴药业集团股份有限公司"), "医疗/医药")
        self.assertEqual(ci.classify_company_industry("TCL中环"), "能源/化工")
        self.assertEqual(ci.classify_company_industry("TCL实业控股"), "制造/工业")

    def test_unknown_returns_none(self):
        self.assertIsNone(ci.classify_company_industry("某某集团"))
        self.assertIsNone(ci.classify_company_industry(""))

    def test_gate_allows_and_blocks(self):
        self.assertFalse(ci.job_industry_allowed("农夫山泉", ["互联网"]))  # 跨行业拦
        self.assertTrue(ci.job_industry_allowed("字节跳动", ["互联网"]))   # 同行业放
        self.assertTrue(ci.job_industry_allowed("农夫山泉", []))           # 没填行业放
        self.assertTrue(ci.job_industry_allowed("某某集团", ["互联网"]))   # 判不出放


class SourceIndustryGateTest(unittest.TestCase):
    def test_source_gate_with_exempt(self):
        # 跨行业源被拦。
        self.assertFalse(discovery.source_industry_ok("农夫山泉", ["互联网"], []))
        # 手动指名公司（exempt）豁免：即便跨行业也放行（与 scoring.ts「公司命中不挡」同口径）。
        self.assertTrue(discovery.source_industry_ok("农夫山泉", ["互联网"], ["农夫山泉"]))
        # 同行业正常放行；用户没填行业放行。
        self.assertTrue(discovery.source_industry_ok("字节跳动", ["互联网"], []))
        self.assertTrue(discovery.source_industry_ok("农夫山泉", [], []))


if __name__ == "__main__":
    unittest.main()
