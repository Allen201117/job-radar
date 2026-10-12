"""地点里的几个字碰巧是别名表里的城市名，不等于岗位在那个城市（2026-10-12）。

改前 `normalize_city` 是子串折叠：串里只要出现别名表里某个城市的字样就整串换成它，哪怕那几个字是区名
（牡丹江的「西安区」）、新区名（宁波的「杭州湾新区」）、路名（上海的 Beijing East Road），或者是另一个拼音词的
一部分（Changzhou 里的 hangzhou、Xinxiang 里的 xian）。岗位被写成一个它不在的城市，推给不在那里的人。

带「live」的原文取自 2026-10-12 重抓各 adapter 交出来的地点；其余是同一种机制下构造的写法。
"""
import unittest

import geo
import normalizer
from adapters.base import RawJob


class WrongFoldLocationTest(unittest.TestCase):
    def test_district_named_like_another_city_gives_the_city_it_belongs_to(self):
        for raw, expected in (
            ("黑龙江省·牡丹江市·西安区", "牡丹江市"),       # live：北森
            ("辽源市-西安区", "辽源市"),                    # live：wt
            ("吉林省·辽源市·西安区", "辽源市"),
            ("宁波市杭州湾新区", "宁波"),                   # live：Moka 卡片上的一行
            ("宁波杭州湾新区", "宁波"),
            ("浙江省宁波市杭州湾新区", "宁波"),
            ("哈尔滨市利民开发区南京路6号", "哈尔滨市"),    # live：Moka 卡片上的一行
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_alias_spanning_two_place_names_is_not_that_city(self):
        # 「陕西 + 安康」「山西 + 安泽县」「江西 + 安福县」：中间那两个字拼起来是「西安」。
        for raw, expected in (
            ("陕西安康", "安康"),
            ("山西安泽县", "山西"),
            ("江西安福县", "江西"),
            ("陕西安塞区", "陕西"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_pinyin_alias_inside_a_longer_word_is_left_as_written(self):
        # 拼音 / 英文别名按整词认。认不出是哪个城市就原样入库（国家仍判得出），不硬塞一个城市。
        for raw in (
            "Changzhou, Jiangsu, China",                # live：smartrecruiters，改前 → 杭州
            "Changzhou, China",
            "China, , , Jiangsu, , , Changzhou",        # live：workday
            "Xinxiang, Henan Sheng, China",             # live：radancy，改前 → 西安
            "China, , , Shanxi, , , XianYang",          # live：workday（咸阳）
            "China, , , Hunan, , , XiangTan",           # live：workday（湘潭）
            "China, , , Hubei, , , Xiang, Yang",        # live：workday（襄阳）
            "Xiangyang, Hubei",
            "Zhangzhou, China",                         # live：workday（漳州），改前 → 杭州
            "Tongxiang, Zhejiang",                      # live：workday（桐乡），改前 → 西安
            "XIANYANG", "XianNing, Hubei", "CHANGZHOU", "XIANGTAN, HUNAN", "XianJu, Zhejiang",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), raw)

    def test_english_street_named_after_a_city_is_not_that_city(self):
        self.assertEqual(normalizer.clean_location("Beijing East Road, Shanghai"), "上海")
        self.assertEqual(normalizer.clean_location("Shanghai, Beijing East Road"), "上海")
        # 只有路名、没写城市：认不出城市，原样入库。
        self.assertEqual(normalizer.clean_location("1266 Nanjing West Road"), "1266 Nanjing West Road")

    def test_whole_word_pinyin_still_folds(self):
        for raw, expected in (
            ("Hangzhou, Zhejiang, China", "杭州"),
            ("Xi'an, Shaanxi", "西安"),
            ("Xian", "西安"),
            ("CN-Shanghai-Pudong", "上海"),
            ("China, , , Shanghai", "上海"),
            ("Suzhou Industrial Park", "苏州"),
            ("SHANGHAI", "上海"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_words_glued_together_by_the_ats_are_still_read(self):
        # workday 把几段粘在一起写：左边认驼峰的大写处，右边跟着大写字母的照认（「XianYang」是点名排除的，见上一条）。
        # 这几条改前就是对的，不能因为「按整词认」把它们改丢。
        for raw, expected in (
            ("ChinaShandongQingdao266000", "青岛"),                                          # live
            ("LOC3289, Unit, 1002, 10F, No, 99, Yanta, Road, Bei, Lin, , District, , XianChina", "西安"),   # live
            ("SingaporeSingapore627871", "新加坡"),                                          # live
            ("SG, , , SINGAPOREUNITS, 07, 01, TO, 07, 06MARKEN, SGKKI", "新加坡"),           # live
            ("China, , , Remote, , , SuzhouJiangsu, , , Commercial", "苏州"),                # live
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_bare_road_abbreviation_is_not_proof_of_a_street(self):
        # 整词的 Road / Street 才算路名；光秃秃的 St / Lu / Jie 可能是别的东西，不能凭它把城市丢了。
        for raw, expected in (
            ("Shanghai, St. Regis Hotel", "上海"),
            ("Beijing, Lu, Gu", "北京"),
            ("1266 Nanjing Xi Lu", "1266 Nanjing Xi Lu"),      # 方位词 + Lu：南京西路
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_parallel_places_are_recognised_exactly_as_before(self):
        # 认「并列地点」的那条正则没动：折叠放宽的写法不会往多地结果里多加城市。
        for raw, expected in (
            ("XIANGYANG / WUHAN", "武汉"),
            ("WUXIANG / WUHAN", "武汉"),
            ("Changzhou / Suzhou", "苏州"),          # 改前 → 杭州
            ("Shanghai / Nanjing", "上海/南京"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)
                self.assertEqual(normalizer.location_places(raw), expected.split("/"))

    def test_fold_is_kept_when_strict_recognition_finds_no_place(self):
        # 严格识别只在段首 / 省名后面认地名；串里只有园区、机构名时它什么都认不出——这类行维持原来的折叠结果，
        # 不能因为认不出就把原来对的城市改丢。
        for raw, expected in (
            ("大上海地区", "上海"),
            ("华东区上海", "上海"),
            ("张江高科技园区（上海）", "上海"),
            ("高新区西安软件园", "西安"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_fold_is_kept_when_nothing_proves_it_wrong(self):
        # 严格识别认出了别的地方、没认出折出来的城市，但那几个字不是别的地名 / 路名的一部分：维持原来的结果。
        for raw, expected in (
            ("四川天府新区成都片区", "成都"),         # 严格识别只认到省
            ("广东省前海深圳湾", "深圳"),
            ("可在北京 天津 青岛", "北京"),           # 前面带着字的那个城市是真的；改成「天津/青岛」就把它丢了
            ("定岗苏州、无锡、常州", "苏州"),
            ("上海北京", "北京"),                     # 几个城市粘在一起写，不是「上海的北京某某」
            ("南京上海深圳", "上海"),
            ("广州深圳等地", "深圳"),
            ("上海北京两地", "北京"),
            ("宁波杭州区域", "杭州"),
            ("丹鸟速递-浙江业务区-杭州区经理", "杭州"),   # live（Moka 部门名）：「杭州区」是业务片区，不是哪个市的区
            ("陕西-西安区", "西安"),                    # 只写了它自己的省：没有旁证说这是别处的西安区
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_remote_and_nationwide_are_untouched(self):
        for raw, expected in (
            ("Remote United States", "远程"),
            ("China, , , Remote, , , Changzhou, , , Commercial", "远程"),   # live：改前 → 杭州；常州认不出，剩下 remote
            ("湖北多地", "全国"),
            ("全国分配", "全国"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_cleaning_its_own_output_changes_nothing(self):
        for raw in ("黑龙江省·牡丹江市·西安区", "宁波杭州湾新区", "陕西安康", "山西安泽县", "Changzhou, Jiangsu, China",
                    "Beijing East Road, Shanghai", "1266 Nanjing West Road", "四川天府新区成都片区",
                    "黑龙江·牡丹江市·西安区 辽宁·沈阳市", "ChinaShandongQingdao266000", "哈尔滨市利民开发区南京路6号"):
            with self.subTest(raw=raw):
                once = normalizer.clean_location(raw)
                self.assertEqual(normalizer.clean_location(once), once)

    def test_wrong_city_never_survives_next_to_the_real_ones(self):
        # 多地并列里夹着一个「X区」：别的城市照常并列，X 不进结果。
        self.assertEqual(normalizer.clean_location("黑龙江·牡丹江市·西安区 辽宁·沈阳市"), "牡丹江市/沈阳市")
        self.assertEqual(normalizer.clean_location("宁波杭州湾新区、上海市"), "宁波/上海")


class PartOfAnotherPlaceTest(unittest.TestCase):
    """geo.cn_name_is_part_of_another_place：那几个字每一处都只是别的地名 / 路名的一部分吗。"""

    def test_true_when_every_mention_belongs_to_something_else(self):
        for text, name in (
            ("黑龙江省·牡丹江市·西安区", "西安"),        # 后面是「区」
            ("哈尔滨市利民开发区南京路6号", "南京"),     # 后面是「路」
            ("陕西安康", "西安"),                        # 跨在两个地名上
            ("山西安泽县", "西安"),
            ("宁波市杭州湾新区", "杭州"),                # 紧跟在另一个城市后面的「X湾」
        ):
            with self.subTest(text=text):
                self.assertTrue(geo.cn_name_is_part_of_another_place(text, name))

    def test_false_when_one_mention_could_be_the_city_itself(self):
        for text, name in (
            ("可在北京 天津 青岛", "北京"),
            ("上海北京", "北京"),
            ("南京上海深圳", "上海"),                    # 几个城市粘在一起写
            ("广州深圳等地", "深圳"),
            ("宁波杭州区域", "杭州"),
            ("浙江业务区-杭州区经理", "杭州"),           # 「杭州区」不是哪个市的区
            ("牡丹江市·杭州区", "杭州"),
            ("陕西-西安区", "西安"),                     # 串里只有它自己的省
            ("四川天府新区成都片区", "成都"),            # 前面只有省
            ("牡丹江市·西安区、西安办事处", "西安"),     # 第二处是真的
            ("西安区", "西安"),                          # 串里没认出别的地方：没有旁证
            ("牡丹江市", "西安"),                        # 串里根本没有这两个字
        ):
            with self.subTest(text=text):
                self.assertFalse(geo.cn_name_is_part_of_another_place(text, name))


class WrongFoldNormalizeTest(unittest.TestCase):
    def _norm(self, location, regions=None):
        raw = RawJob(company="", title="工程师", location=location, jd_url="https://example.com/jobs/1")
        job = normalizer.normalize(raw, source_id="s", company="Acme", regions=regions or ["CN"])
        return job["location"], job["country_code"], job["job_scope"]

    def test_country_and_scope_stay_domestic(self):
        for raw, location in (
            ("黑龙江省·牡丹江市·西安区", "牡丹江市"),
            ("宁波杭州湾新区", "宁波"),
            ("Changzhou, Jiangsu, China", "Changzhou, Jiangsu, China"),
            ("China, , , Hubei, , , Xiang, Yang", "China, , , Hubei, , , Xiang, Yang"),
            ("Beijing East Road, Shanghai", "上海"),
        ):
            with self.subTest(raw=raw):
                for regions in (["CN"], ["CN", "US", "SG", "Remote"]):
                    self.assertEqual(self._norm(raw, regions), (location, "CN", "domestic"))


if __name__ == "__main__":
    unittest.main()
