"""国聘公告接入的纯函数回归（用例全部来自 2026-09-18 接口实测数据）。不打网络。"""
import unittest
from datetime import date

from announcements.iguopin import (
    _audience, _employer_type, _mentions_place, _province_of, _region, _BANNED_HOSTS,
)


class TestRegionAttribution(unittest.TestCase):
    """⚠️ 归属准确性高于一切：宁可写「未知」，不可写错的地区。"""

    def test_trusts_district_when_title_agrees(self):
        self.assertEqual(_region({
            "districts_cn": ["唐山"], "districts": ["000000.130000.130200"],
            "title": "唐山工业职业技术大学关于2026年选聘高层次人才的公告",
        }), "河北省")

    def test_province_name_also_counts(self):
        # 市名（济南）不在标题里，但省名「山东」在 → 采信，落到省级
        self.assertEqual(_region({
            "districts_cn": ["济南"], "districts": ["000000.370000.370100"],
            "title": "山东大学财务部非事业编制人员招聘公告",
        }), "山东省")

    def test_rejects_iguopin_geocoding_errors(self):
        """国聘按名字自动地理编码，实测会错。对不上就写未知。"""
        # 福州市鼓楼区 → 被编码成开封鼓楼区（两地都有鼓楼区）
        self.assertIsNone(_region({
            "districts_cn": ["开封"], "districts": ["000000.410000.410200.410204"],
            "title": "福州市鼓楼区国有资产投资发展集团有限公司2026年公开招聘公告",
        }))
        # 贵州锦丰矿业 → 被编码成江苏丰县（匹配上了「锦丰」）
        self.assertIsNone(_region({
            "districts_cn": ["徐州"], "districts": ["000000.320000.320300.320321"],
            "title": "贵州锦丰矿业有限公司招聘公告", "main_company_name": "贵州锦丰矿业有限公司",
        }))

    def test_substring_collision_is_not_a_match(self):
        """⚠️ 回归：「五**大连**池」不是大连。裸子串会把一条黑龙江的公告判成辽宁省。"""
        self.assertIsNone(_region({
            "districts_cn": ["大连"], "districts": ["000000.210000.210200"],
            "title": "五大连池风景区教育幼儿园关于招聘5名公益性岗位的公告",
        }))
        self.assertFalse(_mentions_place("五大连池风景区", "大连"))
        self.assertTrue(_mentions_place("大连理工大学招聘", "大连"))
        self.assertTrue(_mentions_place("中化学数科（北京）电子商务", "北京"), "括号后也算词首")

    def test_multi_or_nationwide_is_quanguo(self):
        self.assertEqual(_region({"districts_cn": ["全国"], "districts": []}), "全国")
        self.assertEqual(_region({"districts_cn": ["天津", "大连", "哈尔滨"], "districts": []}), "全国")
        self.assertIsNone(_region({"districts_cn": [], "districts": []}))

    def test_province_code_lookup(self):
        self.assertEqual(_province_of("000000.320000.320300.320321"), "江苏省")
        self.assertIsNone(_province_of(""))
        self.assertIsNone(_province_of(None))


class TestAudience(unittest.TestCase):
    """⚠️ 国聘自己的标签不可信：81/100 打着「校招」，含明显的社招。以标题为准。"""

    def test_society_open_plus_grad_year_is_both(self):
        self.assertEqual(_audience({
            "title": "赣州旅游投资集团2026年社会公开招聘公告",
            "announcement_tags": [{"label": "校招"}], "graduation_years_cn": ["2026"],
        }), "both", "标题说「社会公开招聘」+ 国聘给了 2026 届 —— 两个信号都真，答案是两者皆可")

    def test_no_graduation_requirement_is_not_a_fresh_signal(self):
        """⚠️ `graduation_years_cn` 常填「无毕业年份要求」——意思恰恰相反，不能当应届信号。"""
        self.assertEqual(_audience({
            "title": "某某公司招聘公告", "graduation_years_cn": ["无毕业年份要求"],
            "announcement_tags": [{"label": "校招"}],
        }), "unknown")

    def test_real_graduation_year_is_a_fresh_signal(self):
        self.assertEqual(_audience({
            "title": "某某公司招聘公告", "graduation_years_cn": ["2027"],
        }), "fresh_grad")

    def test_campus_title(self):
        self.assertEqual(_audience({"title": "中国五矿2027校园招聘"}), "fresh_grad")


class TestEmployerType(unittest.TestCase):
    def test_uses_iguopin_category_for_companies(self):
        self.assertEqual(_employer_type({"category_cn": ["中央企业"], "title": "中国五矿2027校园招聘"}), "央企")
        self.assertEqual(_employer_type({"category_cn": ["央企子公司"], "title": "龙源电力校园招聘"}), "央企")
        self.assertEqual(_employer_type({"category_cn": ["地方国企"], "title": "某国资集团招聘"}), "地方国企")

    def test_falls_back_to_title_for_non_company_categories(self):
        # 事业单位 / 教师 / 医疗 交回标题判，与各省人社厅那批同口径
        self.assertEqual(_employer_type({"category_cn": ["教师"], "title": "某某大学招聘公告"}), "高校")
        self.assertEqual(_employer_type({"category_cn": ["医疗"], "title": "某某医院招聘公告"}), "医疗卫生")


class TestBannedHosts(unittest.TestCase):
    def test_third_party_platforms_are_red_line(self):
        for host in ("zhaopin.com", "chinahr.com", "51job.com", "zhipin.com", "liepin.com"):
            self.assertIn(host, _BANNED_HOSTS)


if __name__ == "__main__":
    unittest.main()
