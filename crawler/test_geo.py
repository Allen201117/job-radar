import unittest

from geo import (
    CHINA_CJK_PLACE_MARKERS,
    KOREA_CJK_MARKERS,
    TAIWAN_CJK_MARKERS,
    _STRICT_CJK_PLACES,
    derive_country_code,
    derive_job_scope,
    is_china_location,
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
        """「其他」「全部地区」「发行市场类」不是地名，硬塞进 CN 就是造假。

        「发行市场类」「销售及市场」是漏进 location 字段的部门名，含「市」但不是地名 ——
        这正是「不能写裸后缀规则」的另一半理由。

        ⚠️ 「全国」**刻意判 CN**，不在本列表里：不认它有现在就在发生的代价 ——
        location_in_scope("全国", {"CN"}) 会返回 False，凡是做地区后置过滤的 adapter
        会把这些岗直接丢掉。库里 2,002 行「全国」逐个核过全部来自 TCL / 中国一汽 / 三一
        这类本土公司源（af974a3 实测），判 CN 零误伤。
        「全部地区」「其它」则相反 —— 那是筛选器的占位值不是「全国」，留 None 走源兜底才对。
        """
        for location in ("全部地区", "其他", "其它", "不限",
                         "发行市场类", "销售及市场", "阿里巴巴园区"):
            with self.subTest(location=location):
                self.assertIsNone(derive_country_code(location))
        # 「山东京博」含省名「山东」，判 CN 是对的（山东京博控股就在山东）——
        # 它在这里是提醒：CHINA_CJK_PLACE_MARKERS 是**子串**匹配，与本文件下方
        # _CN_ADMIN_NAMES 的**整段**匹配是两套语义，别把两者的用例互相搬。
        self.assertEqual(derive_country_code("山东京博"), "CN")
        self.assertEqual(derive_country_code("全国"), "CN")

    def test_overseas_unspecified(self):
        """自报「海外」「国外」：没有国家可给，但绝不能走 source.regions 兜底算成国内供给。"""
        for location in ("海外", "国外", "境外", "海外区域", "国外区域", "境外区域"):
            with self.subTest(location=location):
                self.assertIsNone(derive_country_code(location))
                self.assertTrue(is_overseas_unspecified(location))
                self.assertEqual(derive_job_scope(location, {"CN"}), "overseas")
        # 「海外区域」是 live 缺口：中控技术 26 个在招岗这么写，补前判 domestic。
        # 「保定市,海外」这类**混写**仍判 domestic —— 串里有大陆城市，那是对的，别一起改掉。
        self.assertEqual(derive_job_scope("保定市,海外", {"CN"}), "domestic")
        self.assertEqual(derive_country_code("保定市,海外"), "CN")
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


class MultiLocationChinaWinsTest(unittest.TestCase):
    """一岗多地写法里中国优先 —— 那种岗确实有一部分在国内，判成境外等于抹掉国内供给。

    所以 `_looks_like_cn_admin` 排在 `_strict_cjk_country` **之前**。
    这个顺序之所以安全，全靠中文行政区规则是**白名单锚定**的（必须命中大陆省级/地级行政区名），
    而不是「任何 X市 → CN」的裸后缀规则：「大阪市」「新北市」「首尔市」「胡志明市」里
    一个大陆地名都没有，命中不了它，照样落到境外词表。
    ⚠️ 谁把白名单放宽成裸后缀规则，这个顺序立刻就错 —— ChineseAdminDivisionTest
    的红线用例会当场变红，别去改顺序绕过它。
    """

    def test_china_segment_wins_over_foreign_segment(self):
        for location in (
            "柳州市、南非", "保定市,俄罗斯", "墨西哥,长春市", "菲律宾、柳州市",
            "池州市、九江市、摩洛哥", "青岛市、日本、潍坊市",
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "CN")
                self.assertEqual(derive_job_scope(location), "domestic")

    def test_pure_foreign_still_foreign(self):
        # 没有任何大陆地名的串不受影响
        for location, expected in (
            ("大阪市", "JP"), ("新北市", "TW"), ("首尔市", "KR"), ("胡志明市", "VN"),
            # 「咸阳」是陕西地级市，但「咸阳郡」在韩国庆尚南道 —— 郡不在 _ADMIN_SUFFIXES 里
            ("韩国·庆尚南道·咸阳郡", "KR"),
        ):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), expected)


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


class FailSafeExclusionsSurviveMergeTest(unittest.TestCase):
    """「宁可漏判、不可错杀」那几条选词，合并两套实现后必须还在。

    它们不是风格问题：**错判一个大陆岗为境外 = 静默删掉一个在招岗**（location_in_scope
    当场丢弃），而漏判一个境外岗只是回到 code=None、走源 regions 兜底，无害。
    2026-09-05 两个并行 session 各写了一套中文地名实现并合并，本类是那次合并的验收断言 ——
    合并很容易把这种「刻意不收某个词」的决定悄悄冲掉，而它不会报错，只会让岗位消失。
    """

    def test_bare_names_are_not_in_word_lists(self):
        """有重叠风险的地名只收「带后缀」或「繁体」写法，裸名一个都不许进词表。"""
        for bare, table, tname in (
            ("新北", TAIWAN_CJK_MARKERS, "TW"),   # 江苏常州有新北区
            ("连江", TAIWAN_CJK_MARKERS, "TW"),   # 福建福州有连江县
            ("台南", TAIWAN_CJK_MARKERS, "TW"),   # 「邢台南和区」含「台南」
            ("台中", TAIWAN_CJK_MARKERS, "TW"),
            ("台东", TAIWAN_CJK_MARKERS, "TW"),
            ("北海", CHINA_CJK_PLACE_MARKERS, "CN"),  # 日本北海道含「北海」
        ):
            with self.subTest(bare=bare, table=tname):
                self.assertNotIn(bare, table, f"裸「{bare}」不该出现在 {tname} 词表（子串匹配会误杀）")
        # 对应的安全写法必须还在，否则等于把这些地名整个漏掉
        for kept, table in (("新北市", TAIWAN_CJK_MARKERS), ("連江", TAIWAN_CJK_MARKERS),
                            ("台南市", TAIWAN_CJK_MARKERS), ("台中市", TAIWAN_CJK_MARKERS),
                            ("北海市", CHINA_CJK_PLACE_MARKERS)):
            with self.subTest(kept=kept):
                self.assertIn(kept, table)

    def test_korea_deliberately_omits_ambiguous_cities(self):
        """福建有大田县、河南潢川古称光州 —— 少认几个韩国城市无害，认错大陆岗有害。"""
        for name in ("大田", "光州", "汉城"):
            with self.subTest(name=name):
                self.assertNotIn(name, KOREA_CJK_MARKERS)

    def test_strict_table_whole_segment_matching_neutralises_bare_names(self):
        """_STRICT_CJK_PLACES 里确实收了裸「汉城」（首尔旧称），靠**整段精确匹配**才没出事。

        ⚠️ 这是一个只在「整段匹配」前提下才安全的词条：一旦有人把 _strict_cjk_country
        改成子串匹配，「武汉城市圈」会立刻被判成韩国。本测试就是那道闸。
        """
        self.assertIn("汉城", _STRICT_CJK_PLACES["KR"])
        for location in ("武汉城市圈", "武汉城市圈产业基地", "湖北省·武汉市"):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "CN")

    def test_live_strings_that_would_break_if_exclusions_were_dropped(self):
        """线上真实地点串（2026-09-05 香港库实测），任一排除项被冲掉就会变成境外。"""
        for location, jobs in (
            ("江苏省·常州市·新北区", 19), ("常州市-新北区", 6),
            ("福建省·福州市·连江县", 3),
            ("广西壮族自治区·北海市", 22), ("广西·北海市", 5), ("北海市", 5),
            ("邢台南和区", None), ("福建省·三明市·大田县", None),
        ):
            with self.subTest(location=location, jobs=jobs):
                self.assertEqual(derive_country_code(location), "CN")
        # 反向：真正的境外同名地必须仍判境外
        self.assertEqual(derive_country_code("北海道"), "JP")
        self.assertEqual(derive_country_code("日本·北海道"), "JP")
        self.assertEqual(derive_country_code("新北市"), "TW")


class UsStateAbbrMustBeUppercaseTest(unittest.TestCase):
    """州缩写必须**大写**这条不是洁癖，是挡住一整类误判的唯一依据。

    2026-09-05 实测：把规则放宽到小写，全库仍无国家的在招岗里会有 802 个被误命中 ——
        "Melbourne" → ne=内布拉斯加     "Mollsfeld, Meerbusch, Germany" → ny=纽约
        "Gurgaon, Haryana, India" → ia=爱荷华   "Bangkok, Bangkok, Thailand" → nd=北达科他
        "Bogot, Bogota, Colombia" → ia   "Work, From, Home" → me=缅因   "Lehi" → hi=夏威夷
    而真正的小写「City, st」槽位在全库是 **0 条**（同日实测）——
    也就是说要求大写**零代价**，放宽则立刻把哥伦比亚/德国/印度/泰国的岗算成美国。
    """

    def test_lowercase_tail_is_not_a_state(self):
        for location in (
            "Melbourne", "Irvine", "Lehi", "Work, From, Home",
            "Mollsfeld, Meerbusch, Germany", "Gurgaon, Haryana, India",
            "Bangkok, Bangkok, Thailand", "Bogot, Bogota, Colombia",
            "Johns, Creek, Georgia",
        ):
            with self.subTest(location=location):
                self.assertNotEqual(derive_country_code(location), "US")

    def test_uppercase_tail_still_works(self):
        for location in ("CHARLOTTE, NC", "Ann, Arbor, MI 48108", "AustinTX"):
            with self.subTest(location=location):
                self.assertEqual(derive_country_code(location), "US")
