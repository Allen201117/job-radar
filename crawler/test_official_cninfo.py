"""巨潮资讯（cninfo）A 股官方披露源解析单测（纯函数，不打网络）。

巨潮 = 中国证监会指定披露平台。按公司名严格匹配 A 股简称 → 代码 + 交易所 → listing 官方事实。
默认关闭（INSIGHT_CNINFO_ENABLED），守"禁猜入库"：上线前须 live 验证返回格式。
"""
import os
import unittest

import official_cninfo as C


class TestExchangeFromCode(unittest.TestCase):
    def test_shanghai(self):
        self.assertEqual(C.exchange_from_code("600519"), "上交所")
        self.assertEqual(C.exchange_from_code("688981"), "上交所")  # 科创板

    def test_shenzhen(self):
        self.assertEqual(C.exchange_from_code("002594"), "深交所")
        self.assertEqual(C.exchange_from_code("300750"), "深交所")  # 创业板

    def test_beijing(self):
        self.assertEqual(C.exchange_from_code("830799"), "北交所")

    def test_unknown(self):
        self.assertEqual(C.exchange_from_code(""), "")
        self.assertEqual(C.exchange_from_code("xyz"), "")


class TestFindStock(unittest.TestCase):
    STOCKS = [
        {"code": "002594", "zwjc": "比亚迪", "orgId": "gssz0002594"},
        {"code": "000001", "zwjc": "平安银行", "orgId": "gssz0000001"},
        {"code": "002352", "zwjc": "顺丰控股", "orgId": "gssz0002352"},
    ]

    def test_exact_match(self):
        self.assertEqual(C.find_stock(self.STOCKS, "比亚迪")["code"], "002594")
        self.assertEqual(C.find_stock(self.STOCKS, "顺丰控股")["code"], "002352")

    def test_suffix_stripped_match(self):
        self.assertEqual(C.find_stock(self.STOCKS, "比亚迪股份有限公司")["code"], "002594")

    def test_no_false_positive(self):
        self.assertIsNone(C.find_stock(self.STOCKS, "中国平安"))  # 平安银行 ≠ 中国平安
        self.assertIsNone(C.find_stock(self.STOCKS, "字节跳动"))

    def test_empty(self):
        self.assertIsNone(C.find_stock([], "比亚迪"))
        self.assertIsNone(C.find_stock(self.STOCKS, ""))


class TestStockToListing(unittest.TestCase):
    def test_builds_fact(self):
        li = C.stock_to_listing({"code": "002594", "zwjc": "比亚迪", "orgId": "gssz0002594"})
        self.assertEqual(li["dimension"], "listing")
        self.assertEqual(li["grade"], "fact")
        self.assertEqual(li["origin"], "official")
        self.assertEqual(li["source_publisher"], "巨潮资讯")
        self.assertEqual(li["payload"]["status"], "listed")
        self.assertEqual(li["payload"]["exchange"], "深交所")
        self.assertEqual(li["payload"]["ticker"], "002594")
        self.assertIn("比亚迪", li["content"])
        self.assertIn("002594", li["source_url"])

    def test_missing_fields_none(self):
        self.assertIsNone(C.stock_to_listing({"code": "002594"}))  # 无 zwjc
        self.assertIsNone(C.stock_to_listing({}))
        self.assertIsNone(C.stock_to_listing(None))


class TestEnabled(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_default_off(self):
        os.environ.pop("INSIGHT_CNINFO_ENABLED", None)
        self.assertFalse(C.enabled())

    def test_on_when_truthy(self):
        os.environ["INSIGHT_CNINFO_ENABLED"] = "true"
        self.assertTrue(C.enabled())


if __name__ == "__main__":
    unittest.main()
