"""上游给的是「城市列表」的 adapter：把每个城市都交出去，不再只取第一个（2026-10-11）。

同日 live 重抓（只读上游返回、不写库）量到的「上游给了不止一个城市、写库只剩第一个」：
字节 1,105 / 12,118，飞书 6 个租户 1,056 / 6,140，小红书 978 / 1,321，阿里 562 / 1,793，
小鹏 376 / 2,182，蔚来 298 / 2,698，小米 195 / 1,446。读侧「地点非空且对不上目标城市」是硬拒，
所以「北京 | 上海」的岗上海的用户在今日推荐里看不到。
"""
import unittest

import normalizer
from adapters import feishu
from adapters.alibaba import AlibabaAdapter
from adapters.bytedance import BytedanceAdapter
from adapters.kuaishou_campus import KuaishouCampusAdapter
from adapters.netease import NeteaseAdapter
from adapters.xiaohongshu import XiaohongshuAdapter


class JoinPlacesTest(unittest.TestCase):
    def test_every_city_is_handed_over_when_cleaning_keeps_them_all(self):
        self.assertEqual(normalizer.join_places(["北京", "上海"]), "北京、上海")
        self.assertEqual(normalizer.clean_location(normalizer.join_places(["北京", "上海"])), "北京/上海")
        self.assertEqual(normalizer.clean_location(normalizer.join_places(["上海市", "北京市", "杭州市"])), "上海/北京/杭州")
        # 都不在别名表里：清洗原样保留，每个城市都还匹配得上。
        self.assertEqual(normalizer.join_places(["保定市", "沈阳市"]), "保定市、沈阳市")

    def test_blank_and_repeated_names_are_dropped(self):
        self.assertIsNone(normalizer.join_places([]))
        self.assertIsNone(normalizer.join_places([None, " "]))
        self.assertEqual(normalizer.join_places(["北京"]), "北京")
        self.assertEqual(normalizer.join_places(["北京", " 北京 ", "上海"]), "北京、上海")

    def test_falls_back_to_the_first_place_when_cleaning_would_lose_one(self):
        # 清洗认不出的地点（境外城市、不带城市名的写法）并进来只会被丢掉，还可能把第一个城市挤掉
        # （「圣何塞、北京」会折成北京）——这时维持改前的做法：只交第一个。
        self.assertEqual(normalizer.join_places(["北京", "圣何塞"]), "北京")
        self.assertEqual(normalizer.join_places(["圣何塞", "北京"]), "圣何塞")
        self.assertEqual(normalizer.join_places(["研发中心", "北京", "上海"]), "研发中心")
        self.assertEqual(normalizer.join_places(["台北", "上海"]), "台北")     # 第一个城市是台湾的照旧被出口拒收

    def test_falls_back_to_the_first_place_when_the_country_would_change(self):
        # 国家码只有一个、按词表顺序取（不是按谁写在前面）：跨国的列表并起来，国家会从第一个城市的换成别的
        # （小米 live：「约翰内斯堡、曼谷」ZA→TH），列表里有台北的还会被出口整行拒收。这类维持只交第一个。
        self.assertEqual(normalizer.join_places(["约翰内斯堡", "曼谷"]), "约翰内斯堡")
        self.assertEqual(normalizer.join_places(["胡志明市", "马尼拉", "台北市", "雅加达"]), "胡志明市")
        self.assertEqual(normalizer.join_places(["新加坡", "上海"]), "新加坡")
        # 同一个国家的几个城市、内地与港澳并列，都不算换国家。
        self.assertEqual(normalizer.join_places(["纽约", "旧金山"]), "纽约、旧金山")
        self.assertEqual(normalizer.join_places(["北京", "香港"]), "北京、香港")
        self.assertEqual(normalizer.join_places(["上海", "新加坡"]), "上海、新加坡")

    def test_falls_back_when_a_name_is_neither_a_known_place_nor_a_known_country(self):
        # 列表里都不是别名表城市时清洗是原样保留，认不出的词会原样进库：裸写的「台中」（台湾词表刻意不收）、部门名。
        self.assertEqual(normalizer.join_places(["保定", "台中"]), "保定")
        self.assertEqual(normalizer.join_places(["保定", "研发中心"]), "保定")
        self.assertEqual(normalizer.join_places(["廊坊", "乌兰察布", "中卫"]), "廊坊、乌兰察布、中卫")

    def test_city_name_with_a_trailing_word_still_counts_as_that_city(self):
        # 腾讯校招的写法「深圳总部 北京 上海」：段首是城市名就认。
        self.assertEqual(normalizer.clean_location(normalizer.join_places(["深圳总部", "北京", "上海"])), "深圳/北京/上海")


class CityListAdaptersTest(unittest.TestCase):
    def test_bytedance_hands_over_the_whole_city_list(self):
        job = BytedanceAdapter()._map({"id": "7641852190756407605", "title": "内容生态运营",
                                       "city_list": [{"name": "北京"}, {"name": "上海"}]})
        self.assertEqual(job.location, "北京、上海")

    def test_bytedance_falls_back_to_city_info_without_a_city_list(self):
        job = BytedanceAdapter()._map({"id": "1", "title": "研究员", "city_info": {"name": "上海"}})
        self.assertEqual(job.location, "上海")

    def _feishu(self):
        adapter = feishu.FeishuGenericAdapter()
        adapter._bind_host("https://campus.dewu.com/578078/position")
        return adapter

    def test_feishu_keeps_city_info_first_then_the_rest_of_the_list(self):
        post = {"id": "1", "title": "供应链专项", "city_info": {"name": "上海"},
                "city_list": [{"name": "上海"}, {"name": "北京"}]}
        self.assertEqual(self._feishu()._map(post).location, "上海、北京")
        # 小米私有部署实测 42 行 city_info 不是 city_list 的第一个：改前写库的是 city_info，它必须还在最前面。
        post = {"id": "1", "title": "供应链专项", "city_info": {"name": "北京"},
                "city_list": [{"name": "南京"}, {"name": "北京"}]}
        self.assertEqual(self._feishu()._map(post).location, "北京、南京")

    def test_feishu_without_city_info_uses_the_whole_list(self):
        post = {"id": "1", "title": "供应链专项实习生", "city_info": None,
                "city_list": [{"name": "杭州"}, {"name": "上海"}]}
        self.assertEqual(self._feishu()._map(post).location, "杭州、上海")

    def test_alibaba_hands_over_every_work_location(self):
        adapter = AlibabaAdapter()
        adapter.company_name = "淘天集团"
        job = adapter._map({"id": 199902900003, "name": "算法工程师", "_host": "talent.taotian.com",
                            "description": "岗位描述", "requirement": "任职要求",
                            "workLocations": ["北京", "杭州", "上海"]})
        self.assertEqual(job.location, "北京、杭州、上海")

    def test_xiaohongshu_hands_over_every_workplace(self):
        job = XiaohongshuAdapter()._map({"positionId": "12345", "positionName": "推荐算法工程师",
                                         "workplace": "北京市，上海市，杭州市"})
        self.assertEqual(job.location, "北京市、上海市、杭州市")
        self.assertEqual(normalizer.clean_location(job.location), "北京/上海/杭州")

    def test_kuaishou_campus_hands_over_every_work_location(self):
        job = KuaishouCampusAdapter()._map({"id": 31711, "name": "算法工程师", "positionStatusCode": "Release",
                                            "workLocationDicts": [{"name": "北京"}, {"name": "杭州"}]})
        self.assertEqual(job.location, "北京、杭州")

    def test_netease_hands_over_every_work_place_name(self):
        job = NeteaseAdapter()._map({"id": 71234, "name": "游戏策划", "workPlaceNameList": ["杭州市", "广州市"]})
        self.assertEqual(job.location, "杭州市、广州市")


if __name__ == "__main__":
    unittest.main()
