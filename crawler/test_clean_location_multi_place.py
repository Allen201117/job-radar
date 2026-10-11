"""多地并列的地点不许折成一个城市（2026-10-11）。

用例里的原文都取自同日 live 重抓各 adapter 交出来的地点（北森「省·市/市」、hotjob「市、市」、wt「市,市」「市-区」、
Moka「市 省·市」），不是编的。改前这些串被 normalize_city 按别名表顺序整串折成**其中一个**城市。
"""
import unittest

import normalizer
from adapters.base import RawJob


class MultiPlaceLocationTest(unittest.TestCase):
    def test_parallel_cities_are_all_kept_in_text_order(self):
        for raw, expected in (
            ("北京市 广东·深圳市 上海市", "北京/深圳/上海"),          # Moka
            ("上海市 广东·深圳市", "上海/深圳"),
            ("北京市、上海市", "北京/上海"),                          # hotjob
            ("福州市、广州市、惠州市、深圳市、苏州市、武汉市", "福州/广州/惠州/深圳/苏州/武汉"),
            ("中山市,广州市", "中山市/广州"),                           # wt
            ("四川省·成都市/乐山市", "成都/乐山市"),                    # 北森
            ("广东省·广州市/深圳市", "广州/深圳"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_city_outside_the_alias_table_is_kept_too(self):
        # 沈阳 / 保定 / 龙岩 不在 CITY_ALIASES 里：改前连「被挑中」的机会都没有。
        # 别名表外的城市保留原文里的「市」字：这类城市单独出现时库里一直是「保定市」这种原样写法，
        # 用户目标填「保定」「保定市」两种都匹配得上（读侧是子串），并列时也得一样。
        self.assertEqual(normalizer.clean_location("吉林·长春市 辽宁·沈阳市"), "长春/沈阳市")
        self.assertEqual(normalizer.clean_location("北京市,上海市,保定市"), "北京/上海/保定市")
        self.assertEqual(normalizer.clean_location("泰州市-高港区,龙岩市-永定区"), "泰州/龙岩市")
        self.assertEqual(normalizer.clean_location("北京、保定、北京市、保定市"), "北京/保定")   # 同一个城市只留第一次出现的写法

    def test_district_under_a_city_is_not_a_second_place(self):
        for raw, expected in (
            ("天津市-东丽区,惠州市,珠海市", "天津市/惠州/珠海"),
            ("郑州市-中原区,苏州市-吴中区", "郑州市/苏州"),
            ("保定市-莲池区,苏州市-张家港市", "保定市/苏州"),
            ("东莞市、佛山市、广州市-南沙区、惠州市", "东莞/佛山/广州/惠州"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_one_place_written_as_a_hierarchy_still_folds_to_the_city(self):
        # 同一个地点的上下级，不是并列：这些行的写库结果必须与改前逐字相同。
        for raw, expected in (
            ("广东省,深圳市,南山区", "深圳"),
            ("江苏省·苏州市·吴中区", "苏州"),
            ("安徽省·合肥市", "合肥"),
            ("北京市·朝阳区", "北京"),
            ("长春市-朝阳区", "长春"),          # 朝阳区是长春的区，不是辽宁朝阳市
            ("苏州市-张家港市", "苏州"),
            ("中国-广东省-深圳市", "深圳"),
            ("广东深圳", "深圳"),
            ("Shenzhen, Guangdong", "深圳"),
            ("Shanghai, Shanghai, China", "上海"),
            ("北京市", "北京"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_english_parallel_cities_become_chinese_names(self):
        # 原样留英文的话，读侧拿中文目标城市做子串匹配对不上（/today 的城市门不认拼音）。
        self.assertEqual(normalizer.clean_location("Shanghai / Beijing"), "上海/北京")
        self.assertEqual(normalizer.clean_location("Beijing, Shanghai"), "北京/上海")
        self.assertEqual(normalizer.clean_location("Hong Kong Shenzhen, Guangdong"), "香港/深圳")

    def test_prefecture_written_as_region_or_autonomous_prefecture_keeps_its_full_name(self):
        # hotjob live：全省地级列表里的「阿里地区」「阿坝藏族羌族自治州」「兴安盟」。裸写成「阿里」「兴安」既认不回来
        # （「阿里」多半指阿里巴巴，只认带后缀的写法），目标填全称的用户也对不上。
        self.assertEqual(
            normalizer.clean_location("成都市,拉萨市,阿里地区,阿坝藏族羌族自治州,海南藏族自治州,兴安盟,其它"),
            "成都/拉萨市/阿里地区/阿坝藏族羌族自治州/海南藏族自治州/兴安盟")

    def test_cleaning_its_own_output_changes_nothing(self):
        # 库里的值会被再清洗（刷新链按城市筛、回填脚本）：清洗两遍必须和一遍一样，否则每过一遍丢一个城市。
        for raw in ("北京市 广东·深圳市 上海市", "吉林·长春市 辽宁·沈阳市", "长春市、大庆市、哈尔滨市、吉林市",
                    "成都市,拉萨市,阿里地区,阿坝藏族羌族自治州,海南藏族自治州,兴安盟", "北京市,河北省",
                    "天津市-东丽区,惠州市,珠海市", "Hong Kong Shenzhen, Guangdong", "中国香港 新加坡 山东·青岛市",
                    "辽宁省朝阳市、北京市", "广东省·深圳市", "厦门市-思明区", "全国多地"):
            with self.subTest(raw=raw):
                once = normalizer.clean_location(raw)
                self.assertEqual(normalizer.clean_location(once), once)

    def test_jilin_city_is_a_city_not_the_province(self):
        # 吉林省与吉林市同名：带「市」的是城市。当成省的话，旁边有长春（本省城市）它就被当作上下级吞掉。
        # hotjob live：「长春市、大庆市、哈尔滨市、吉林市」。
        self.assertEqual(normalizer.clean_location("长春市、大庆市、哈尔滨市、吉林市"), "长春/大庆市/哈尔滨市/吉林市")
        self.assertEqual(normalizer.location_places("吉林省·长春市 吉林省·吉林市"), ["长春", "吉林市"])
        self.assertEqual(normalizer.location_places("吉林省吉林市"), ["吉林市"])
        self.assertEqual(normalizer.clean_location("吉林省·长春市"), "长春")

    def test_english_street_named_after_a_city_is_not_that_city(self):
        # workday live：上海南京西路的门牌地址。「Nanjing Road」是路名，不是南京。
        for raw in ("China, , Shanghai, , Unit, 02, 07, 15th, Floor, 688, West, Nanjing, Road, Jing'an",
                    "Nanjing Road, Shanghai", "1266 Nanjing Rd West, Shanghai", "Nanjing East Road, Shanghai"):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), "上海")
        self.assertEqual(normalizer.clean_location("Shanghai / Nanjing"), "上海/南京")

    def test_province_without_its_own_city_stays_as_a_place(self):
        self.assertEqual(normalizer.clean_location("北京市,河北省"), "北京/河北")

    def test_filler_words_between_places_are_dropped(self):
        self.assertEqual(normalizer.clean_location("杭州市、其它、宁波市"), "杭州/宁波")

    def test_location_without_alias_city_is_left_exactly_as_it_was(self):
        # 行里没有别名表里的城市：改前就是原样入库、每个城市都匹配得上，这次一个字都不动。
        for raw in ("内蒙古·包头市 辽宁·沈阳市", "厦门市-思明区", "山西 山西·大同市", "哥伦比亚 厄瓜多尔"):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), raw)

    def test_remote_and_nationwide_keep_their_old_result(self):
        for raw, expected in (
            ("全国多地", "全国"),
            ("Remote - Shanghai", "上海"),
            ("United States - Remote", "远程"),
            ("Remote", "远程"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected)

    def test_the_city_the_old_fold_picked_is_always_still_there(self):
        # 改前折成城市 A 的行，改后 A 必须还在（读侧按子串匹配，A 的用户不能因为这次改动看不到岗）。
        for raw in ("北京市 广东·深圳市 上海市", "深圳市,广州市,惠州市,武汉市,苏州市,福州市", "Shanghai / Beijing",
                    "黑龙江省·牡丹江市·西安区", "宁波杭州湾新区", "全国多地（北京、上海）", "Xiangyang, Hubei / Wuhan"):
            with self.subTest(raw=raw):
                old_city = normalizer.normalize_city(raw)
                self.assertIn(old_city, normalizer.clean_location(raw).split("/"))


class MultiPlaceNormalizeTest(unittest.TestCase):
    def _norm(self, location, title="工程师", regions=None):
        raw = RawJob(company="", title=title, location=location, jd_url="https://example.com/jobs/1")
        return normalizer.normalize(raw, source_id="s", company="Acme", regions=regions or ["CN"])

    def test_multi_city_row_is_domestic_with_every_city_in_location(self):
        job = self._norm("北京市 广东·深圳市 上海市")
        self.assertEqual((job["location"], job["country_code"], job["job_scope"]), ("北京/深圳/上海", "CN", "domestic"))

    def test_adapter_location_still_wins_over_title_city(self):
        self.assertEqual(self._norm("上海市、南京市", title="销售经理-杭州")["location"], "上海/南京")


if __name__ == "__main__":
    unittest.main()
