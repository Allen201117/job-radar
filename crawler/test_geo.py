import unittest

from geo import (
    derive_country_code,
    derive_job_scope,
    is_overseas_unspecified,
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
    """中文行政区地名识别（2026-09-05 加）。

    背景：CHINA_LOCATION_MARKERS 以拼音为主，中文标记只有十几个直辖市/省会 + 「中国」，
    所以 "Changchun" 认得、「长春市」认不得。live 实测（香港库 active 岗）中文地点（非远程）
    269,431 个岗里 **68,838 个（25.5%）抽不出国家**，只能靠 source.regions 兜底 ——
    哪天某个源被放开 US，这些中国岗会静默翻成 overseas，且不报错。

    🚫 本类存在的首要理由是**红线**，不是覆盖率：直接写「含 省/市/区/县 后缀 → CN」会把
    新北市/大阪市/首尔市/蔚山广域市/平壤市/胡志明市 全判成中国。台日韩朝越那几条断言
    删一条都不行。
    """

    def test_foreign_admin_suffix_never_becomes_cn(self):
        for location, expected in (
            ("新北市", "TW"), ("台北市", "TW"), ("高雄市", "TW"), ("台中市", "TW"), ("桃园市", "TW"),
            ("大阪市", "JP"), ("東京都", "JP"), ("东京都", "JP"), ("京都市", "JP"), ("横滨市", "JP"),
            ("首尔市", "KR"), ("蔚山广域市", "KR"), ("大田广域市", "KR"), ("光州广域市", "KR"),
            ("韩国·忠清北道·忠州市", "KR"),
            ("平壤市", "KP"),
            ("胡志明市", "VN"), ("越南·胡志明市", "VN"),
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), expected)
                self.assertNotEqual(derive_country_code(location), "CN")
                # 台湾按项目口径不归入任一范围；日韩朝越也不该混进国内看板
                self.assertFalse(location_in_scope(location, {"CN"}))
                self.assertEqual(derive_job_scope(location), "overseas")

    def test_four_chinese_writing_forms(self):
        """founder 报的四类缺失写法，各给正例（岗数取自 2026-09-05 香港库实测）。"""
        cases = {
            # ① 省·市间隔号
            "安徽省·芜湖市": "CN", "福建·宁德市": "CN", "山东省·潍坊市·高密市": "CN",
            # ② 裸市名不带省
            "长春市": "CN", "嘉兴": "CN", "惠州市": "CN", "东莞": "CN", "济南": "CN",
            # ③ 市-区连字符
            "保定市-莲池区": "CN", "衡阳市-衡南县": "CN", "泰州市-高港区": "CN",
            # ④ 省级与自治州
            "广东省": "CN", "内蒙古自治区": "CN", "昌吉回族自治州": "CN",
            "昌吉回族自治州-昌吉市": "CN", "大理白族自治州": "CN",
            "红河哈尼族彝族自治州-弥勒市": "CN", "西藏·阿里地区": "CN", "雄安新区": "CN",
        }
        for location, expected in cases.items():
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), expected)
                self.assertTrue(location_in_scope(location, {"CN"}))

    def test_chinese_places_are_not_stolen_by_foreign_tables(self):
        """中文地名互为子串的坑 —— 这些全是线上真实岗，判错就是把中国岗踢出国内看板。

        「新北」→ 江苏常州有新北区（25 岗）；「朝鲜」→ 吉林延边朝鲜族自治州（32 岗）；
        「连江」→ 福州连江县（4 岗，而台湾马祖也叫连江县）；「九龙」→ 重庆九龙坡区（30 岗）。
        所以境外中文地名一律**整段精确匹配**，且只收含后缀的完整形态（"新北市" 而非 "新北"）。
        """
        for location in (
            "江苏省·常州市·新北区", "常州市-新北区",
            "吉林省·延边朝鲜族自治州·延吉市", "延边朝鲜族自治州",
            "吉林省·白山市·长白朝鲜族自治县", "福建省·福州市·连江县",
            "重庆市-九龙坡区", "重庆市·九龙坡区",
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "CN")

    def test_non_place_strings_stay_unknown(self):
        """「全国」「其他」「发行市场类」不是地名，硬塞进 CN 就是造假。

        「全国」保持 None 交给 source.regions 兜底（CN 源 → domestic），比拍脑袋判 CN 诚实。
        「发行市场类」「销售及市场」是漏进 location 字段的部门名，含「市」但不是地名 ——
        这正是「不能写裸后缀规则」的另一半理由。
        """
        for location in ("全国", "全部地区", "其他", "其它", "不限",
                         "发行市场类", "销售及市场", "阿里巴巴园区", "山东京博"):
            with self.subTest(location=location):
                self.assertIsNone(derive_country_code(location))

    def test_overseas_unspecified(self):
        """自报「海外」「国外」：没有国家可给，但绝不能走 source.regions 兜底算成国内供给。"""
        for location in ("海外", "国外", "境外"):
            with self.subTest(location=location):
                self.assertIsNone(derive_country_code(location))
                self.assertTrue(is_overseas_unspecified(location))
                self.assertEqual(derive_job_scope(location, {"CN"}), "overseas")
        self.assertFalse(is_overseas_unspecified("上海"))
        self.assertFalse(is_overseas_unspecified("海外市场部经理"))  # 整段匹配，不是子串
        # ⚠️「全球」刻意**不算** overseas：它字面包含中国，判 overseas 会把国内岗踢走。
        # 与「全国」同归非地名，交给 source.regions 决定 —— 宁可不表态，不要表错态。
        self.assertFalse(is_overseas_unspecified("全球"))
        self.assertEqual(derive_job_scope("全球", {"CN"}), "domestic")

    def test_hongkong_segments(self):
        self.assertEqual(derive_country_code("新界"), "HK")
        self.assertEqual(derive_country_code("九龙"), "HK")
        self.assertEqual(derive_job_scope("新界"), "domestic")


class GeoCrossLanguageFixtureTest(unittest.TestCase):
    """与 lib/geo.js 共读同一份夹具，逐条断言两侧输出一致。

    只靠注释「改一边必须改另一边」挡不住漂移，线上已经出过一次：TW 在 Python 侧
    2026-07-28 就补了，JS 侧一直缺 → "Taipei, Taiwan, Province of China" 在 JS 里判成 CN。
    夹具在 tests/fixtures/geo-cases.json，JS 侧断言在 tests/geo.test.js。
    """

    def test_matches_shared_fixture(self):
        import json
        import os

        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures", "geo-cases.json"
        )
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertGreater(len(doc["cases"]), 100, "夹具被清空了？")
        for case in doc["cases"]:
            with self.subTest(location=case["location"], note=case["note"]):
                self.assertEqual(derive_country_code(case["location"]), case["expected"])


class UsStateTest(unittest.TestCase):
    """美国州名 / 州缩写（2026-09-05 加）。

    US 词表原本只有十几个大城市，认不出州。live 实测（香港库 active 岗）英文地点 132,876 个岗里
    24,672 个抽不出国家，**其中 11,753 个被判成 domestic** —— 用户筛「国内」会看到
    Mossville, Illinois / Irving, Texas / CHARLOTTE, NC。改后 20,579 个岗判出 US，
    其中 8,192 个从 domestic 翻成 overseas。

    🚫 两字母缩写不能裸认：IN=印度 / DE=德国 / CA=加拿大 / TN=印度泰米尔纳德邦 / GA=格鲁吉亚。
    只在「City, ST」这个位置、且原串是**大写**时才认。
    """

    def test_state_codes_at_tail(self):
        for location in (
            "CHARLOTTE, NC", "Florence, KY", "Memphis, TN", "Ann, Arbor, MI",
            "Ann, Arbor, MI 48108", "Merrimack, NH", "Smithfield, RI",
            # 某个 adapter 会把逗号吃掉，州缩写黏在城市后面
            "AustinTX", "Santa, ClaraCA", "PhoenixAZ", "GloucesterMA",
            # 同一个 adapter 还会把 ZIP+4 写成 "55403, 2542"
            "1000, Nicollet, Mall, MinneapolisMN, 55403, 2542",
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "US")
                self.assertEqual(derive_job_scope(location), "overseas")

    def test_state_full_names(self):
        for location in (
            "Mossville, Illinois", "Irving, Texas", "Portage, Michigan",
            "La, Crosse, Wisconsin", "Nashville, Tennessee", "Lafayette, Indiana",
            "Indiana, , , Indianapolis", "Virginia, , , Mclean", "St, Paul, Minnesota",
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "US")

    def test_state_codes_do_not_steal_other_countries(self):
        """改前 ", ca" / ", ma" / ", wa" 是**裸子串** token，把这些全判成了美国。

        ", ca" 命中 ", Capital"、", ma" 命中 ", Manulife" / ", Maharashtra"、
        ", wa" 命中 ", Wan"（香港湾仔/长沙湾的地址）。线上实测 92 行，其中 43 行是香港地址。
        """
        for location in (
            "Chennai, TN, in", "Pune, Maharashtra, in",          # 印度（TN 也是泰米尔纳德邦）
            "Montreal, QC, ca", "Toronto, ON, CAN", "Toronto, Canada",
            "Warsaw, Masovian, PL, 02-677",
            "Søborg, Capital Region of Denmark, DK",
            "Buenos Aires, Capital Federal, AR, C1107CBE",
            "Subang Jaya, Selangor, Malaysia",
            "Taguig, National, Capital, Region, Manila, Philippines",
            "Taikoo, Shing, 12, Taikoo, Wan, Road",              # 香港太古城
            "Sydney, NSW",                                       # 三字母，不该命中
        ):
            with self.subTest(location=location):
                self.assertNotEqual(derive_country_code(location), "US")

    def test_georgia_is_deliberately_not_a_state_name(self):
        """"georgia" 与格鲁吉亚同名，收了就会把第比利斯的岗算成美国。宁可漏认。"""
        self.assertIsNone(derive_country_code("Tbilisi, Georgia"))

    def test_chinese_rules_unaffected(self):
        # 州规则排在最后，任何显式国名/中文地名都优先于它
        self.assertEqual(derive_country_code("长春市"), "CN")
        self.assertEqual(derive_country_code("Beijing, China"), "CN")
        self.assertEqual(derive_country_code("大阪市"), "JP")
