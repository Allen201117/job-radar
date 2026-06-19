import unittest

from adapters.china_location import is_china_company_location


class ChinaCompanyLocationTest(unittest.TestCase):
    def test_accepts_structured_mainland_and_hk_macau_locations(self):
        for location in (
            "沈阳市",
            "河北雄安新区",
            "嘉兴市",
            "广东省-湛江市",
            "全国多省区",
            "香港特别行政区",
        ):
            with self.subTest(location=location):
                self.assertTrue(is_china_company_location(location))

    def test_rejects_taiwan_and_overseas_locations(self):
        for location in (
            "台北",
            "台湾省",
            "东京",
            "伦敦",
            "新加坡",
            "利雅得",
            "圣保罗",
        ):
            with self.subTest(location=location):
                self.assertFalse(is_china_company_location(location))


if __name__ == "__main__":
    unittest.main()
