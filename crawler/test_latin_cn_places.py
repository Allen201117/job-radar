"""拼音 / 英文写法的国内地点认成中文地级市（2026-10-12）。

❌ 外企招聘系统给的国内地点是拼音（「Changzhou, Jiangsu, China」「Tianjin, TJ, CN, 300457」），别名表只有约 28 个城市的拼音，
   其余原样入库；读侧城市判断只做中文匹配，「地点非空且对不上目标城市」是硬拒，真正在那个城市的用户也看不到。
✅ 全国地级市拼音表（lib/cn-prefecture-pinyin.json）+ geo.latin_cn_places，判法见那里的注释。

夹具 tests/fixtures/latin-cn-location-cases.json 是 2026-10-12 live 重抓 943 条源 29.0 万行里全部「国内 + 纯拉丁」写法
（378 种，逐条读过）：认得出的写成什么、认不出的原样留着，一条不落。
"""
import json
import os
import unittest

import geo
import normalizer
from adapters.base import RawJob

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
with open(os.path.join(_ROOT, "tests", "fixtures", "latin-cn-location-cases.json"), encoding="utf-8") as _f:
    FIXTURE = json.load(_f)
with open(os.path.join(_ROOT, "lib", "cn-prefecture-pinyin.json"), encoding="utf-8") as _f:
    PINYIN = json.load(_f)
with open(os.path.join(_ROOT, "lib", "cn-province-prefectures.json"), encoding="utf-8") as _f:
    PREFECTURES = json.load(_f)


def _norm(location, declared=None, regions=("CN", "US", "SG", "Remote")):
    kw = dict(company="", title="工程师", location=location, jd_url="https://example.com/jobs/1")
    raw = RawJob(**kw, country_code=declared) if declared else RawJob(**kw)
    job = normalizer.normalize(raw, source_id="s", company="Acme", regions=list(regions))
    return job["location"], job["country_code"], job["job_scope"]


class PinyinTableTest(unittest.TestCase):
    def test_every_prefecture_has_an_entry_and_nothing_else(self):
        expected = set(PREFECTURES["municipalities"]) - {"香港", "澳门"}
        for names in PREFECTURES["provinces"].values():
            expected.update(names)
        self.assertEqual(set(PINYIN["cities"]), expected)
        self.assertEqual(set(PINYIN["provinces"]), set(PREFECTURES["provinces"]))

    def test_two_cities_spelled_the_same_both_need_their_province(self):
        # 泰州 / 台州、福州 / 抚州、宜春 / 伊春、玉林 / 榆林、苏州 / 宿州：串里没写省就分不开，谁都不许裸认。
        # 苏州是例外——它在别名表里（两端同表，改它是另一件事），所以只要求宿州带省。
        by_spelling = {}
        for name, entry in PINYIN["cities"].items():
            for form in entry["latin"]:
                by_spelling.setdefault(geo._latin_letters(form), set()).add(name)
        clashes = {key: names for key, names in by_spelling.items() if len(names) > 1}
        self.assertEqual(set(clashes), {"taizhou", "fuzhou", "yichun", "yulin", "suzhou"})
        for names in clashes.values():
            for name in names - {"苏州"}:
                with self.subTest(name=name):
                    self.assertTrue(PINYIN["cities"][name].get("needs_province"))

    def test_no_city_is_spelled_like_a_province(self):
        provinces = {geo._latin_letters(f) for e in PINYIN["provinces"].values() for f in e["latin"]}
        cities = {geo._latin_letters(f) for e in PINYIN["cities"].values() for f in e["latin"]}
        self.assertEqual(provinces & cities, set())

    def test_written_name_keeps_the_short_name_in_front(self):
        # 读侧按子串比：目标填短名（「恩施」）的用户必须匹配得上写进库的名字。
        for name, entry in PINYIN["cities"].items():
            if "written" in entry:
                with self.subTest(name=name):
                    self.assertTrue(entry["written"].startswith(name))

    def test_written_name_reads_back_unchanged(self):
        # 写进库的名字再清洗一遍不许变，和别的城市并列时也一样（多地并列会走中文那套严格识别，
        # 「伊犁哈萨克自治州」「神农架林区」「定安县」它读不回来 → 这几个写短名；审查推演出来的，见 CLAUDE.md）。
        for name, entry in PINYIN["cities"].items():
            if not entry["latin"]:
                continue
            written = normalizer.CITY_ALIASES.get(name) or entry.get("written") or name + "市"
            other = "北京" if written == "上海" else "上海"
            for text in (written, f"{written}/{other}", f"{other}/{written}"):
                with self.subTest(text=text):
                    self.assertEqual(normalizer.clean_location(text), text)

    def test_every_city_is_recognised_by_its_own_spelling(self):
        # 词表里每个写法 + 它的省 → 认回它自己（拼音写错、正则拼错、省对不上都会在这里红）。
        index = geo._load_province_index()[0]
        province_latin = {p: e["latin"][0].replace("_", " ") for p, e in PINYIN["provinces"].items()}
        for name, entry in PINYIN["cities"].items():
            province = index[name]
            tail = f", {province_latin[province].title()}, China" if province in province_latin else ", China"
            for form in entry["latin"]:
                for spelling in {form.replace(" ", "").replace("_", " "), form.replace("_", " ") + " Shi"}:
                    with self.subTest(name=name, spelling=spelling):
                        cities = geo.latin_cn_places(spelling.title() + tail)[0]
                        self.assertEqual([c[1] for c in cities], [name])

    def test_province_codes_do_not_collide(self):
        codes = [e["code"] for e in PINYIN["provinces"].values()] + list(PINYIN["municipality_codes"])
        self.assertEqual(len(codes), len(set(codes)))


class RealSpellingsTest(unittest.TestCase):
    def test_every_live_spelling_cleans_to_the_reviewed_result(self):
        for case in FIXTURE["cases"]:
            with self.subTest(raw=case["raw"]):
                self.assertEqual(normalizer.clean_location(case["raw"]), case["want"])

    def test_cleaning_the_result_again_changes_nothing(self):
        for case in FIXTURE["cases"]:
            with self.subTest(raw=case["raw"]):
                self.assertEqual(normalizer.clean_location(case["want"]), case["want"])

    def test_country_and_scope_are_what_the_raw_text_says(self):
        # 认成中文之后国家码 / 求职范围不许变：闸门就是「这串自己判得出是中国」。
        for case in FIXTURE["cases"]:
            with self.subTest(raw=case["raw"]):
                location, country, scope = _norm(case["raw"])
                self.assertEqual(location, case["want"])
                self.assertEqual(country, geo.derive_country_code(case["raw"]))
                self.assertEqual((country, scope), ("CN", "domestic"))

    def test_bare_city_is_recognised_once_the_ats_says_it_is_in_china(self):
        for case in FIXTURE["declared_cn"]:
            with self.subTest(raw=case["raw"]):
                self.assertEqual(normalizer.clean_location(case["raw"]), case["raw"])   # 自己没说国家：清洗不认
                self.assertEqual(_norm(case["raw"], declared="CN"), (case["want"], "CN", "domestic"))


class LatinCnRulesTest(unittest.TestCase):
    def _clean(self, pairs):
        for raw, expected in pairs:
            with self.subTest(raw=raw):
                self.assertEqual(normalizer.clean_location(raw), expected or raw)

    def test_chinese_spellings_never_go_through_the_pinyin_table(self):
        self._clean((raw, None) for raw in (
            "江苏省·常州市·武进区", "常州市", "保定市-莲池区", "安徽省·芜湖市", "福建·厦门市", "重庆市", "天津市",
            "常州 Changzhou", "厦门市 Xiamen, Fujian",
        ))

    def test_text_must_say_china_by_itself(self):
        self._clean((
            ("Zibo", None),                               # 不在国家词表里的裸城市名：判不出是中国
            ("Anyang, Gyeonggi-do, South Korea", None),   # 韩国安养
            ("Aksu, Kazakhstan", None),
            ("Canton, Ohio", None),
            ("Zhongshan District, Taipei, Taiwan", None),
            ("Zibo, China", "淄博市"),
            ("Zibo, Shandong", "淄博市"),
        ))

    def test_roads_districts_and_counties_are_not_the_city(self):
        self._clean((
            ("No.251 Changzhi Road, Taiyuan, Shanxi, China", "太原市"),
            ("Zhongshan Dong Road, Shijiazhuang, Hebei, China", "石家庄市"),
            ("Hulun Buir South Road, Hohhot, Inner Mongolia, China", "呼和浩特市"),
            ("Chaoyang District, Beijing, China", "北京"),
            ("Changsha County, Hunan, China", None),      # 长沙县：宁可不认，「X District / County」多半不是那个地级市
            ("Changsha, Xian, China", "长沙市/西安"),     # 逗号隔开的是并列的两个城市，不是「长沙县」
            ("Jinan City, Shandong, China", "济南市"),
        ))

    def test_city_name_inside_a_street_building_or_school_is_not_the_city(self):
        # 城市名要独占一段。只读审查构造的反例（2026-10-12）：当天 29 万行真实数据里恰好没有，
        # 但第一版实现会把它们认成「中山市/广州」「哈尔滨市/威海市」「北京/深圳」——比不认更糟。
        self._clean((
            ("Zhongshan Er Lu, Guangzhou, Guangdong, China", "广州"),
            ("No. 2 Zhongshan 3rd Road, Yuexiu District, Guangzhou, Guangdong, China", "广州"),
            ("Zhongshan Memorial Hall, Guangzhou, Guangdong, China", "广州"),
            ("Zhongshan Da Dao Xi, Guangzhou, Guangdong, China", "广州"),
            ("Harbin Institute of Technology, Weihai, China", "威海市"),
            ("Peking University Shenzhen Graduate School, Shenzhen, China", "深圳"),
            ("Xianyang Hotel, Taiyuan, Shanxi, China", "太原市"),
            ("Zhongshan Park, Dalian, China", "大连市"),
            ("Zhongshan, Dalian, China", "大连市"),          # 大连中山区：中山要写着广东才认
            ("Da Lian Shi, Jin Zhou Xin Qu, Liao Ning Sheng, China", "大连市"),   # 金州新区
            ("Dalian Jinzhou, Liaoning, China", None),       # 两个名字挤在一段里：都不认
            ("China_Dalian_Plant", None),                    # 站点代号
            ("Tianjin Exchange Tower 2", None),              # live：楼名。少认这 1 行，换上面那些不被认错
        ))
        # 段里只有国家词 / 省名 / Shi / City / 数字的照认
        self._clean((
            ("China Yancheng, MFG 1 (KUM)", "盐城市"),       # live：workday 54 行
            ("Hohhot China (Jiutai) (0C99)", "呼和浩特市"),
            ("Jinan City 2, CN", "济南市"),
            ("Dalian-Liaoning-China", "大连市"),
            ("China > Jiaxing : 681 Shengtang Road", "嘉兴市"),
            ("Tianjin (Teda)", "天津市"),
        ))

    def test_xian_followed_by_another_syllable_is_not_xian_the_city(self):
        self._clean((
            ("Xian Yang Shi, Shaan Xi Sheng, China", "咸阳市"),
            ("Xian Ning Shi, Hu Bei Sheng, China", "咸宁市"),
            ("Xian, Shaanxi, China", "西安"),
            ("Xian Gaoxin, Shaanxi, China", "西安"),
        ))

    def test_letters_outside_ascii_do_not_break_the_lookup(self):
        # re.I 下「ı」会匹配 i：没有 re.A 时正则认得出、按连写拼音查表查不到，KeyError 拖垮整个源。
        self.assertEqual(normalizer.clean_location("Qıngdao, China"), "Qıngdao, China")

    def test_a_named_province_or_municipality_must_be_its_own(self):
        self._clean((
            ("Baoshan, Shanghai", "上海"),                # 宝山区
            ("Zhongshan Park, Shanghai, China", "上海"),
            ("Changzhou, Zhejiang, China", None),         # 常州不在浙江：宁可不认
            ("Zhongshan, Guangdong", "中山市"),
            ("Zhongshan, GD, CN", "中山市"),
            ("Tianjin, TJ, CN, 300457", "天津市"),
            ("China, Shanxi, XianYang", "咸阳市"),        # Shanxi 常被拿来写陕西
        ))

    def test_names_that_collide_need_their_province(self):
        self._clean((
            ("Taizhou, China", None),
            ("Taizhou, Zhejiang, China", "台州市"),
            ("Taizhou, Jiangsu", "泰州"),
            ("Fuzhou", None),
            ("Fuzhou, Fujian, China", "福州"),
            ("Fuzhou, Jiangxi, China", "抚州市"),
            ("Yulin, Guangxi", "玉林市"),
            ("Yulin, Shaanxi, China", "榆林市"),
            ("Dali, China", None),
            ("Dali, Yunnan, China", "大理白族自治州"),
            ("Chaoyang, Liaoning, China", "朝阳市"),
            ("Chaoyang, China", None),
            ("Suzhou, Anhui, China", "苏州"),             # 别名表认过的位置听别名表的（实测没有这种写法）
        ))

    def test_syllables_written_apart_need_shi_or_the_province(self):
        self._clean((
            ("He Fei Shi, An Hui Sheng, China", "合肥"),
            ("Yang Pu Qu, Shang Hai Shi, China", "上海"),
            ("Su Zhou Shi, An Hui Sheng, China", "宿州市"),
            ("Bao Ding, Hebei, China", "保定市"),
            ("Da Li, China", None),
            ("Shang Hai, China", None),
            ("Ji'nan, CN, 250102", "济南市"),             # 撇号不算拆开写
            ("Bayan Nur, CN", "巴彦淖尔市"),              # 本来就是两个词的英文名
            ("Ürümqi, Xinjiang, China", "乌鲁木齐市"),
        ))

    def test_only_a_province_is_written(self):
        self._clean((
            ("Jiangsu, China", "江苏"),
            ("China, HA, Henan", "河南"),
            ("Zhejiang Sheng, China", "浙江"),
            ("Shanxi, China", None),                      # Shanxi 常被拿来写陕西：不替它定是哪个省
            ("GZ, CN", None),                             # 只有两字母码：GZ 在公司里常指广州，码表里是贵州
            ("HN, CN", None),
            ("Taicang, Jiangsu", None),                   # 县级市：写成「江苏」反而丢信息
            ("China, Guangdong, Virtual", None),
            ("Jiangsu, Zhejiang, China", None),           # 两个省
            ("China", None),
        ))

    def test_several_places(self):
        self._clean((
            ("XIANGYANG / WUHAN", "襄阳市/武汉"),
            ("Changzhou / Suzhou", "常州市/苏州"),
            ("Dalian, Liaoning, China; Shenyang, Liaoning, China", "大连市/沈阳市"),
            ("Shanghai, China; Changzhou, China", "上海"),   # 串里点了上海、没点江苏：不认常州
        ))

    def test_recogniser_reports_position_province_and_written_name(self):
        cities, provinces = geo.latin_cn_places("China, Hubei, Enshi")
        self.assertEqual(cities, ((14, "恩施", "恩施土家族苗族自治州", "湖北"),))
        self.assertEqual(provinces, ("湖北",))
        self.assertEqual(geo.latin_cn_places("江苏省常州市"), ((), ()))
        self.assertEqual(geo.latin_cn_places("Urumqi"), ((), ()))
        self.assertEqual(geo.latin_cn_places("Urumqi", True)[0], ((0, "乌鲁木齐", "乌鲁木齐市", "新疆"),))


class MokaEnglishLineTest(unittest.TestCase):
    """Moka 卡片的地点行要先问「写进库之后每个城市还在不在」（china_ats._survives_location_cleaning）。
    拼音行现在会被认成中文城市，行里的省这一段（Jiangsu）不能被当成一个丢了的地点。"""

    def test_city_with_its_province_is_still_written(self):
        from adapters import china_ats
        for line, places in (
            ("Changzhou, Jiangsu, China", ["Changzhou", "Jiangsu", "China"]),
            ("Jinan, Shandong", ["Jinan", "Shandong"]),
            ("Zhengzhou, Henan Sheng, China", ["Zhengzhou", "Henan Sheng", "China"]),
            ("Tianjin / Dalian", ["Tianjin", "Dalian"]),
        ):
            with self.subTest(line=line):
                self.assertTrue(china_ats._survives_location_cleaning(line, places))

    def test_line_that_would_lose_a_place_is_not_written(self):
        from adapters import china_ats
        # 太仓是县级市、拼音表不认：整行写成「常州市」就把它丢了，宁可不写地点（城市未知）。
        self.assertFalse(china_ats._survives_location_cleaning("Changzhou, Taicang", ["Changzhou", "Taicang"]))


class DeclaredCountryTest(unittest.TestCase):
    def test_only_a_declared_cn_turns_a_bare_name_into_a_city(self):
        self.assertEqual(_norm("Urumqi"), ("Urumqi", None, "domestic"))
        self.assertEqual(_norm("Urumqi", declared="CN"), ("乌鲁木齐市", "CN", "domestic"))
        self.assertEqual(_norm("Anyang", declared="KR"), ("Anyang", "KR", "overseas"))

    def test_declared_cn_does_not_settle_a_name_that_needs_its_province(self):
        for raw in ("Dali", "Fuzhou", "Taizhou"):
            with self.subTest(raw=raw):
                self.assertEqual(_norm(raw, declared="CN"), (raw, "CN", "domestic"))


if __name__ == "__main__":
    unittest.main()
