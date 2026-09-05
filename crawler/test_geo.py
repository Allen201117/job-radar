import unittest

from geo import (
    derive_country_code,
    derive_job_scope,
    is_china_location,
    location_in_scope,
)


class TestDeriveCountryCode(unittest.TestCase):
    def test_china_cities(self):
        self.assertEqual(derive_country_code("Beijing, China"), "CN")
        self.assertEqual(derive_country_code("上海"), "CN")
        self.assertEqual(derive_country_code("Hong Kong"), "HK")

    def test_us_cities(self):
        self.assertEqual(derive_country_code("New York, NY"), "US")
        self.assertEqual(derive_country_code("Sunnyvale, CA, United States"), "US")
        self.assertEqual(derive_country_code("Seattle"), "US")

    def test_singapore(self):
        self.assertEqual(derive_country_code("Singapore"), "SG")

    def test_remote_with_country(self):
        cases = (
            ("Remote - US", "US"),
            ("Remote, US", "US"),
            ("US - Remote", "US"),
            ("US Remote", "US"),
            ("Remote (USA)", "US"),
            ("Remote - United States", "US"),
            ("Remote, USA", "US"),
            ("Remote (US)", "US"),
            ("Remote (U.S.)", "US"),
            ("Remote - Singapore", "SG"),
            ("Remote, SG", "SG"),
            ("Singapore - Remote", "SG"),
            ("Remote (Singapore)", "SG"),
        )
        for location, expected in cases:
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), expected)

    def test_country_code_tokens_do_not_match_substrings(self):
        self.assertEqual(derive_country_code("Business Analyst, Beijing"), "CN")
        self.assertEqual(derive_country_code("Focus Group, Shanghai"), "CN")
        self.assertIsNone(derive_country_code("Belarus"))

    def test_bare_remote_unknown(self):
        self.assertIsNone(derive_country_code("Remote"))

    def test_unknown(self):
        self.assertIsNone(derive_country_code(""))
        self.assertIsNone(derive_country_code("Multiple Locations"))

    def test_iso_country_code_cn(self):
        """外企 ATS 给小写国别码 + 空格分词拼音城市，只有认 "cn" 才判得出中国。

        这几个串是 SmartRecruiters 上大陆集团中国岗的原样地点（2026-09-05 live 抓取）。
        城市 "He Fei Shi" 与拼音表里的 "hefei" 按词边界对不上 ⇒ code=None ⇒
        location_in_scope 落「非远程且无国家」的 False 分支 ⇒ 中国岗被当成非中国岗丢掉。
        29 个中国岗里 8 个（28%）就是这么丢的。
        """
        for location in (
            "He Fei Shi, An Hui Sheng, cn",
            "Ning Bo Shi, Zhe Jiang Sheng, cn",
            "Ji Ning Shi, Shan Dong Sheng, cn",
            "Yang Pu Qu, Shang Hai Shi, cn",
            "Zhangjiagang, cn",
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "CN")
                self.assertTrue(location_in_scope(location, {"CN", "US", "SG", "Remote"}))

    def test_iso_cn_does_not_leak_into_other_places(self):
        # "cn" 只在独立成词时算国别码；也别抢走港澳台的归属
        self.assertNotEqual(derive_country_code("Cincinnati, OH"), "CN")
        self.assertNotEqual(derive_country_code("Chennai, TN, in"), "CN")
        self.assertEqual(derive_country_code("Hong Kong, cn"), "HK")
        self.assertEqual(derive_country_code("Taipei, Taiwan, Province of China"), "TW")


class TestDeriveJobScope(unittest.TestCase):
    def test_greater_china_is_domestic(self):
        self.assertEqual(derive_job_scope("Beijing, China"), "domestic")
        self.assertEqual(derive_job_scope("Hong Kong"), "domestic")
        self.assertEqual(derive_job_scope("澳门"), "domestic")

    def test_overseas(self):
        self.assertEqual(derive_job_scope("New York, NY"), "overseas")
        self.assertEqual(derive_job_scope("Singapore"), "overseas")
        for location in ("Remote - US", "US Remote", "Remote (USA)", "Remote - Singapore"):
            with self.subTest(location=location):
                self.assertEqual(derive_job_scope(location), "overseas")

    def test_bare_remote_defaults_domestic(self):
        self.assertEqual(derive_job_scope("Remote"), "domestic")

    def test_unknown_defaults_domestic(self):
        self.assertEqual(derive_job_scope(""), "domestic")


class TestLocationInScope(unittest.TestCase):
    def test_default_cn_matches_today(self):
        self.assertTrue(location_in_scope("Beijing, China", {"CN"}))
        self.assertTrue(location_in_scope("Hong Kong", {"CN"}))
        self.assertFalse(location_in_scope("New York", {"CN"}))
        self.assertFalse(location_in_scope("Singapore", {"CN"}))

    def test_overseas_regions(self):
        self.assertTrue(location_in_scope("New York", {"US"}))
        self.assertTrue(location_in_scope("Singapore", {"SG"}))
        self.assertFalse(location_in_scope("London", {"US", "SG"}))

    def test_remote_region(self):
        self.assertTrue(location_in_scope("Remote - US", {"US"}))
        self.assertTrue(location_in_scope("Remote", {"Remote"}))

    def test_multi_region(self):
        self.assertTrue(location_in_scope("Beijing", {"CN", "US", "SG"}))
        self.assertTrue(location_in_scope("Singapore", {"CN", "US", "SG"}))

    def test_taiwan_is_not_in_any_active_scope(self):
        for loc in ("Taiwan", "Taipei, Taiwan", "台北, 台湾"):
            with self.subTest(loc=loc):
                self.assertFalse(location_in_scope(loc, {"CN"}))
                self.assertFalse(location_in_scope(loc, {"US", "SG", "Remote"}))
                self.assertFalse(location_in_scope(loc, {"CN", "US", "SG", "Remote"}))


if __name__ == "__main__":
    unittest.main()


class TaiwanWithChinaSuffixTest(unittest.TestCase):
    """台湾写成「Taiwan, Province of China」时不许被当成 CN 放行。

    2026-07-28 Siemens 改成翻全分页后实测捞进 5 个台北岗才暴露：TW 压根不在 _COUNTRY_TOKENS 里，
    这种写法含 "china" → derive_country_code 判成 CN → 进了国内看板。
    上面的 test_taiwan_is_not_in_any_active_scope 只覆盖不含 china 字样的写法（code=None
    自然落 False），盖不住这个洞。
    """

    VARIANTS = (
        "Taipei, Taipei shih, Taiwan, Province of China",
        "Taiwan, Province of China",
        "Hsinchu, Taiwan, Province of China",
        "台北, 台湾, 中国",
    )

    def test_not_in_scope_for_any_region_set(self):
        for loc in self.VARIANTS:
            with self.subTest(loc=loc):
                self.assertFalse(location_in_scope(loc, {"CN"}))
                self.assertFalse(location_in_scope(loc, {"CN", "US", "SG", "Remote"}))

    def test_country_code_is_tw_not_cn(self):
        for loc in self.VARIANTS:
            with self.subTest(loc=loc):
                self.assertEqual(derive_country_code(loc), "TW")

    def test_mainland_and_hongkong_still_work(self):
        # 别为了拦台湾误伤大陆/港澳
        self.assertEqual(derive_country_code("Shanghai, Shanghai Shi, China"), "CN")
        self.assertEqual(derive_country_code("Wuxi, Jiangsu Sheng, China"), "CN")
        self.assertEqual(derive_country_code("Hong Kong"), "HK")
        self.assertTrue(location_in_scope("Wuxi, Jiangsu Sheng, China", {"CN"}))
        self.assertTrue(location_in_scope("Hong Kong", {"CN"}))


class BareRemoteScopeBySourceRegionsTest(unittest.TestCase):
    """裸「远程」按**源的 regions** 兜底判归属。

    2026-09-04 实测：全库 9,873 个「裸远程 + 判 domestic」的在招岗里，**9,863 个来自
    regions 不含 CN 的海外源**（AbbVie 1,512 / ServiceNow 576 / Samsara 483 / NVIDIA 360…），
    只有 10 个来自纯 CN 源 —— 用户筛「国内」时看到的是一片美国远程岗。分离度 99.9%。
    （带国家写法的「Remote - US」早已由 f306271 修好，这里补的是裸远程那一半。）
    """

    def test_bare_remote_from_overseas_source_is_overseas(self):
        self.assertEqual(derive_job_scope("远程", {"US", "SG", "Remote"}), "overseas")
        self.assertEqual(derive_job_scope("Remote", {"US", "SG", "Remote"}), "overseas")

    def test_bare_remote_from_source_including_cn_stays_domestic(self):
        """源含 CN 就可能是真国内远程岗，不许判 overseas（宁可漏判不可错杀）。"""
        self.assertEqual(derive_job_scope("远程", {"CN", "US", "SG", "Remote"}), "domestic")
        self.assertEqual(derive_job_scope("远程", {"CN"}), "domestic")

    def test_omitting_regions_keeps_legacy_behaviour(self):
        """老调用方不传 regions → 行为一字不变，避免这次改动波及别的链路。"""
        self.assertEqual(derive_job_scope("远程"), "domestic")
        self.assertEqual(derive_job_scope(""), "domestic")

    def test_explicit_location_always_wins_over_source_regions(self):
        """地点能抽出国家时以地点为准 —— 海外源里的北京岗仍是国内岗，反之亦然。"""
        self.assertEqual(derive_job_scope("Beijing, China", {"US", "SG"}), "domestic")
        self.assertEqual(derive_job_scope("香港", {"US"}), "domestic")
        self.assertEqual(derive_job_scope("New York, NY", {"CN", "US"}), "overseas")

    def test_unknown_location_from_overseas_source_is_overseas(self):
        """空地点 / Multiple Locations 与裸远程同理，都走源兜底。"""
        self.assertEqual(derive_job_scope("", {"US"}), "overseas")
        self.assertEqual(derive_job_scope("Multiple Locations", {"US"}), "overseas")


class ChineseAdminDivisionTest(unittest.TestCase):
    """中文地名要判得出国家，别把 6.9 万个中国岗的归属押在 sources.regions 一个字段上。

    2026-09-05 实测：库里 27.8 万个「中文地点 + 在招」的岗里 8.3 万个 country_code 为空 ——
    旧词表的中文标记只有「中国」+21 个一线城市，认得 "Changchun" 却认不得「长春市」。
    这些岗全靠 derive_job_scope 的「抽不出国家就问源」兜底，哪天某个源被放开成 {CN,US}
    （海外扩展一直在做这件事），它名下这批岗会**静默**翻成 overseas，不报错、只是国内供给少一块。

    下面四类写法是缺口里最大的四桶（按在招岗数）。
    """

    CASES = (
        # 省·市 / 省-市 分隔写法
        "安徽省·芜湖市", "福建·宁德市", "江苏·常州市", "山东省-济南市", "安徽省-芜湖市",
        # 裸市名
        "长春市", "嘉兴", "惠州市", "柳州市", "衡阳市", "保定市",
        # 市-区 / 省·市·区 三级
        "保定市-莲池区", "安徽省·芜湖市·鸠江区", "泰州市-高港区", "山东省·潍坊市·高密市",
        # 省级 / 自治区 / 自治州
        "广东省", "江苏省", "山西省", "内蒙古自治区·呼和浩特市", "广西壮族自治区·南宁市",
        "昌吉回族自治州", "昌吉回族自治州-昌吉市", "巴音郭楞蒙古自治州",
        # 本土源的「全国」写法：不认它的代价是 location_in_scope 返回 False，
        # 做地区后置过滤的 adapter 会把这些岗当成「不在 CN 范围」丢掉。
        "全国",
    )

    def test_code_is_cn(self):
        for loc in self.CASES:
            with self.subTest(loc=loc):
                self.assertEqual(derive_country_code(loc), "CN")

    def test_scope_and_filter(self):
        for loc in self.CASES:
            with self.subTest(loc=loc):
                self.assertEqual(derive_job_scope(loc), "domestic")
                self.assertTrue(location_in_scope(loc, {"CN"}))
                # 地点自己说得清国家时，源 regions 不该翻盘（海外源里的中国岗仍是国内岗）
                self.assertEqual(derive_job_scope(loc, {"US", "SG"}), "domestic")


class ForeignCjkPlaceIsNotChinaTest(unittest.TestCase):
    """台/日/韩的中文地名一个都不许判成中国 —— 这是补中文词表的红线。

    「地点含 省/市/区/县/自治州 → 中国」这条规则能覆盖 84% 的缺口，很诱人，但会把
    新北市 / 大阪市 / 東京都 / 首尔市 一起判成中国。台湾按项目口径**不抓、不归入任一范围**，
    所以中文词表只认真实存在的大陆行政区名，并把 TW/JP/KR 词表一起补上兜底。
    """

    TW = ("新北市", "台北市", "臺北市", "桃園市", "桃园市", "臺中市", "台中市", "臺南市",
          "台南市", "高雄市", "基隆市", "新竹市", "嘉义市", "苗栗县", "彰化县", "南投县",
          "云林县", "屏东县", "宜兰县", "花莲县", "臺東縣", "澎湖县", "金门县", "台湾省")
    JP = ("大阪市", "東京都", "东京", "京都市", "横滨市", "札幌市", "名古屋市", "北海道",
          "神奈川县", "福冈市", "日本·东京")
    KR = ("首尔市", "首爾", "釜山", "仁川", "大邱", "蔚山", "京畿道", "韩国·首尔")

    def test_not_china(self):
        for group, expected in ((self.TW, "TW"), (self.JP, "JP"), (self.KR, "KR")):
            for loc in group:
                with self.subTest(loc=loc):
                    self.assertEqual(derive_country_code(loc), expected)
                    self.assertNotEqual(derive_job_scope(loc), "domestic")

    def test_not_in_any_scope_we_crawl(self):
        # 台湾不属于任何 regions；日韩不在放开的 US/SG/Remote 里 —— 都不该被放行
        for loc in self.TW + self.JP + self.KR:
            with self.subTest(loc=loc):
                self.assertFalse(location_in_scope(loc, {"CN"}))
                self.assertFalse(location_in_scope(loc, {"CN", "US", "SG", "Remote"}))

    def test_is_china_location_rejects_taiwan_with_china_suffix(self):
        """is_china_location 是外企 adapter「只留在华岗」的那道门，台湾不许从这里漏进来。

        「Taipei, Taiwan, China」含 "china"，旧实现按 marker 扫描判成在华（库里实测 1 行）。
        """
        for loc in ("Taipei, Taiwan, China", "Taipei, Taiwan, Province of China",
                    "台北, 台湾, 中国", "东京", "首尔"):
            with self.subTest(loc=loc):
                self.assertFalse(is_china_location(loc))
        # 只做减法：大陆 / 港澳照旧
        for loc in ("Shanghai, China", "Greater China", "China - Remote", "Hong, Kong",
                    "Asia-Pacific-China-Beijing", "长春市", "安徽省·芜湖市"):
            with self.subTest(loc=loc):
                self.assertTrue(is_china_location(loc))


class MainlandLookalikeTest(unittest.TestCase):
    """长得像台/日/韩、其实是大陆的写法，一个都不许被误杀。

    错判方向不对称：**漏判一个台湾岗**只是回到 code=None，非远程照样被 location_in_scope
    丢掉（无害）；**错判一个大陆岗**是把在招岗静默删掉（有害）。下面每条都是库里真实存在的写法
    （2026-09-05 全库 19,728 个地点写法逐个对拍得出）。
    """

    def test_mainland_names_that_contain_foreign_place_names(self):
        cases = (
            # 江苏常州有「新北区」，所以 TW 只收「新北市」不收裸「新北」（库里 55 行）
            "江苏省·常州市·新北区", "常州市-新北区", "常州-新北区",
            # 福建福州有「连江县」，所以 TW 只收繁体「連江」（库里 4 行）
            "福建省·福州市·连江县", "福建省·福州市·连江县/罗源县",
            # 广西「北海市」是日本「北海道」的前缀，所以 CN 只收「北海市」不收裸「北海」
            "广西壮族自治区·北海市", "北海市", "广西·北海市", "北海市-银海区",
            # 「邢台南和区」粘连出「台南」，所以 TW 的简体台南只收「台南市」
            "河北省·邢台市·南和区", "邢台南和区",
        )
        for loc in cases:
            with self.subTest(loc=loc):
                self.assertEqual(derive_country_code(loc), "CN")
                self.assertTrue(location_in_scope(loc, {"CN"}))

    def test_multi_location_string_keeps_china(self):
        """一岗多地写法里混进外国国名，不许因此把中国岗翻成海外。

        这就是 JP/KR 排在 CN **后面**、而 TW 排在前面的原因（TW 要压过「Province of China」）。
        """
        for loc in ("青岛市、日本、潍坊市", "长沙市,铜仁市,钦州市,印度尼西亚,贵阳市,韩国"):
            with self.subTest(loc=loc):
                self.assertEqual(derive_country_code(loc), "CN")
                self.assertEqual(derive_job_scope(loc), "domestic")
