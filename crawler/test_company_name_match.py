"""公司名归属核验单测（纯函数，不打网络）。

守的是 CLAUDE.md「归属准确性高于一切」：关键词类源（国聘/搜索）返回的是法人实体全称，
朴素子串匹配会把无关公司抓进来。下面的反例全部来自 2026-07-26 国聘 live 实测。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from company_name_match import company_name_matches


class CompanyNameMatchTest(unittest.TestCase):
    def test_token_at_start_is_accepted(self):
        self.assertTrue(company_name_matches("泰康人寿保险有限责任公司天津分公司", "泰康"))
        self.assertTrue(company_name_matches("中远海运物流供应链有限公司西南分公司", "中远海运"))
        self.assertTrue(company_name_matches("华图教育科技有限公司青岛分公司", "华图"))

    def test_place_prefix_only_is_accepted(self):
        self.assertTrue(company_name_matches("陕西圆通速递有限公司", "圆通"))
        self.assertTrue(company_name_matches("北京京东方松彩创新有限公司", "京东方"))
        self.assertTrue(company_name_matches("中国石油工程建设有限公司天津分公司", "中国石油"))
        self.assertTrue(company_name_matches("上海中远海运工程物流有限公司", "中远海运"))

    def test_extra_words_before_token_are_rejected(self):
        # 中通快递 vs 北京华晋中通电力工程设计——「华晋」不是地名，属于不同公司
        self.assertFalse(company_name_matches("北京华晋中通电力工程设计有限公司", "中通"))
        self.assertFalse(company_name_matches("中交城投绿城（广东）城市运营管理有限公司珠海分公司", "绿城"))
        self.assertFalse(company_name_matches("山东中卓华图教育文化科技发展有限责任公司青岛分公司", "华图"))

    def test_token_absent_is_rejected(self):
        self.assertFalse(company_name_matches("中冶一局环境科技有限公司", "中国中冶"))
        self.assertFalse(company_name_matches("", "圆通"))
        self.assertFalse(company_name_matches("陕西圆通速递有限公司", ""))


if __name__ == "__main__":
    unittest.main()
