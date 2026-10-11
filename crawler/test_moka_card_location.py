"""Moka 岗位卡的地点与标题解析（_parse_moka_card）。

治的病（2026-10-11 香港库在招 Moka 岗 46,685 行实测）：
  · 地点靠「标题之后第一条 ≤12 字、含 省/市/区 的短行」猜 → 带「区 / 市」字样的部门名、职能类别、正文句子被写进
    location（「广东大区」135 行、「发行市场类」117 行、「进行市场调查和分析；」……共 896 行 / 117 种取值），
    而真正的地点字段排在它们后面取不到。
  · 标题开头的「新 / 热 / 急」一律当角标剥掉 →「热管理工程师」入库成「管理工程师」、「新媒体运营」成「媒体运营」。

夹具 fixtures/moka_cards.json 是同日从线上门户抓的卡片 innerText **原文**，每张卡的期望值是对着卡片人工写的。
钉两个方向：① 不是地点的不许写进去；② 是地点的不许丢。
"""
import json
import os
import unittest

import normalizer
from adapters.base import RawJob
from adapters.china_ats import MokaAdapter, _moka_card_fields, _moka_places, _parse_moka_card, _split_moka_title

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "moka_cards.json")


def _load_cards():
    with open(_FIXTURE, encoding="utf-8") as f:
        return {c["id"]: c for c in json.load(f)["cards"]}


CARDS = _load_cards()


def _card(*lines):
    return "\n".join(lines)


def _normalized(card_id):
    """卡片 → 解析 → 入库清洗（与 run.py 同一条链），返回写库的那一行。"""
    location, title = _parse_moka_card(CARDS[card_id]["text"])
    url = "https://app.mokahr.com/social-recruitment/t/1#/job/x"
    raw = RawJob(company="测试公司", title=title, location=location, job_type=None, summary=None,
                 jd_url=url, apply_url=url, posted_at=None)
    return normalizer.normalize(raw, source_id="s", company="测试公司", regions={"CN"})


class MokaCardFixtureTest(unittest.TestCase):
    def test_every_real_card(self):
        self.assertGreaterEqual(len(CARDS), 35, "夹具被清空了？下面的循环会空转着通过")
        for card in CARDS.values():
            with self.subTest(card=card["id"], why=card["why"]):
                location, title = _parse_moka_card(card["text"])
                self.assertEqual(location, card["location"])
                self.assertEqual(title, card["title"])

    def test_fixture_covers_both_directions(self):
        # 只有「该丢的丢了」或只有「该留的留了」都不算数。
        kept = [c for c in CARDS.values() if c["location"]]
        dropped = [c for c in CARDS.values() if c["location"] is None]
        self.assertGreaterEqual(len(kept), 15)
        self.assertGreaterEqual(len(dropped), 15)


class MokaCardFieldsTest(unittest.TestCase):
    """字段区怎么切：正文一行都不许混进来。"""

    def _fields(self, card_id):
        lines = [ln.strip() for ln in CARDS[card_id]["text"].splitlines() if ln.strip()]
        _title, rest, _badge = _split_moka_title(lines)
        return _moka_card_fields(rest)

    def test_new_layout_fields_stop_before_the_body(self):
        fields, marked, below = self._fields("dept-region-before-location")
        self.assertEqual((fields, marked), (["华北区域", "全职", "天津市"], True))
        self.assertTrue(below.startswith("职位介绍"), "字段区下面那一行是正文，交回去由调用方判")

    def test_salary_is_a_field_even_though_it_is_not_doubled(self):
        # 薪资不带省略提示、只渲染一遍；它后面跟着「|」，照样算字段。
        self.assertEqual(self._fields("salary-dept-type-category-location")[0],
                         ["12 - 20 K/月", "云贵战区", "全职", "酒店总经理岗位", "云南·昆明市"])

    def test_zero_field_new_layout_card_has_no_fields(self):
        self.assertEqual(self._fields("zero-field-card-body-follows-title"), ([], False, None))

    def test_body_that_lists_cities_line_by_line_is_not_read_as_fields(self):
        # 新版、没配置字段，正文逐行列城市：读成「广州」就把北京、上海的用户挡在外面了。
        for card in (_card("校园大使", "发布于 2026-10-01", "招聘城市", "北京", "上海", "广州"),
                     _card("校园大使", "招聘城市", "北京", "上海", "广州")):       # 没有发布日期行、行数超过老版卡片
            with self.subTest(card=card):
                self.assertEqual(_parse_moka_card(card), (None, "校园大使"))

    def test_old_layout_takes_both_lines(self):
        self.assertEqual(self._fields("old-layout-glued-tags-then-location"), (["全职市场类", "广东·深圳市"], False, None))

    def test_location_on_its_own_line_below_the_fields(self):
        # 福瑞泰克 / 阳光电源校招：字段区里没有地点，地点单独在下面一行，再往下才是正文或投递说明。
        self.assertEqual(self._fields("location-line-below-the-fields")[2], "浙江·杭州市")
        card = _card("感知算法工程师", "研究院", "研究院", "|", "全职", "全职", "上海市", "允许1个月内投递2个职位", "立即投递")
        self.assertEqual(_parse_moka_card(card), ("上海市", "感知算法工程师"))

    def test_line_below_the_fields_is_ignored_when_the_last_field_is_the_location(self):
        card = _card("销售经理", "发布于 2026-10-01", "全职", "全职", "|", "天津市", "天津市", "上海")
        self.assertEqual(_parse_moka_card(card), ("天津市", "销售经理"))

    def test_only_the_last_field_of_a_new_layout_card_can_be_the_location(self):
        # 微医的部门就叫「三明」「山东」，后面是「全职」：部门不是地点。
        card = _card("客服专员", "发布于 2026-09-01", "5 - 7 K/月", "|", "三明", "三明", "|", "全职", "全职")
        self.assertEqual(_parse_moka_card(card), (None, "客服专员"))

    def test_legacy_single_rendered_fields_with_separators(self):
        # 2026-06 的排版：字段不重复、用「|」分隔，最后跟「立即投递」。
        card = _card("急", "全栈开发工程师", "发布于 2026-06-05", "全职", "|", "信息技术类", "|", "上海市", "立即投递")
        self.assertEqual(_parse_moka_card(card), ("上海市", "全栈开发工程师"))

    def test_body_line_that_merely_starts_with_fabu_is_not_a_date_line(self):
        # 「发布」开头的不都是发布日期：老版卡片的标签行可以叫「发布运营类」。
        self.assertEqual(_moka_card_fields(["发布运营类", "上海市", "发布时间：2026-05-20"]),
                         (["发布运营类", "上海市"], False, None))


class MokaPlaceLineTest(unittest.TestCase):
    """整行是不是地点字段。两张表里的值全部取自线上卡片 / 库里被写错的 location。"""

    def test_location_lines(self):
        for line in ("上海市", "四川·成都市", "上海市·黄浦区", "河南省", "内蒙古自治区", "香港", "中国香港", "新加坡",
                     "缅甸·仰光", "英国 德国", "马来西亚 浙江·宁波市",
                     "广东·广州市  新加坡  北京市", "Shenzhen, Guangdong", "Hong Kong"):
            with self.subTest(line=line):
                self.assertTrue(_moka_places(line))

    def test_departments_categories_and_body_sentences(self):
        for line in ("广东大区", "川渝大区", "东南战区", "华东战区（浙江）", "华北区域", "山东区域", "河南省公司",
                     "浙江业务区", "海外区域", "发行市场类", "全职市场类", "销售及市场", "国内市场体系",
                     "亚太区仓库运营管理部", "中国区生产运营管理部", "大中华区盖世威事业部", "微医天津",
                     "广东区销售 Guangdong Sales", "上海服务 Shanghai Service", "广东区", "浙江区", "北京区",
                     "徐州重型机械有限公司", "松下电器（中国）有限公司", "进行市场调查和分析；", "研或加强区域协作。",
                     "关于两个岗位的区别", "base 萧山市区", "负责市场：汕头+揭阳", "江苏、浙江等省的县级市",
                     "全职", "其它", "R&D", "Market", "Full-time", "China Sales", "12 - 20 K/月", "2"):
            with self.subTest(line=line):
                self.assertIsNone(_moka_places(line))

    def test_lines_that_name_no_city_are_not_written(self):
        # 只写国家 / 只写省名 / 「海外其他」：写进去就是把岗从填了城市的用户那里藏掉，还会盖掉标题里更准的城市。
        for line in ("中国", "全国", "China", "PRC", "中国 China", "湖北", "河南", "湖北 湖南", "海外其他"):
            with self.subTest(line=line):
                self.assertIsNone(_moka_places(line))

    def test_vague_place_next_to_a_real_city_is_kept(self):
        for line in ("江苏·徐州市 中国", "山西 山西·大同市", "海外其他 广东·深圳市"):
            with self.subTest(line=line):
                self.assertTrue(_moka_places(line))

    def test_taiwan_is_still_written_so_the_exit_gate_can_reject_it(self):
        # 台湾不抓：地点必须照常交出去，出口的质量门才拒得掉；当成「说不到城市」吞掉，它就按国内岗入库了。
        for line in ("台湾省", "台湾", "台湾·台北市", "Taiwan"):
            with self.subTest(line=line):
                location, title = _parse_moka_card(_card("岗位", "发布于 2026-10-01", "全职", "全职", "|", line, line))
                self.assertEqual(location, line)
                url = "https://app.mokahr.com/social-recruitment/t/1#/job/x"
                raw = RawJob(company="测试公司", title=title, location=location, job_type=None, summary=None,
                             jd_url=url, apply_url=url, posted_at=None)
                self.assertEqual(normalizer.validate_job_quality(raw, url.split("#")[0]),
                                 (False, "rejected region (taiwan)"))

    def test_province_written_with_its_suffix_keeps_the_old_behaviour(self):
        # 牧原校招的地点就是「河南省」「辽宁省」：改前一直在写，这次不动。
        self.assertEqual(_parse_moka_card(CARDS["province-only"]["text"])[0], "河南省")

    def test_english_places_split_on_space_but_not_on_comma(self):
        self.assertEqual(_moka_places("Hong Kong Shenzhen, Guangdong"), ["hong kong", "shenzhen, guangdong"])


class MokaMultiPlaceTest(unittest.TestCase):
    """多地并列：写进库之后页面上列的每个地点都得还匹配得上，丢一个就有城市的用户看不到这个岗（读侧对不上是硬拒）。"""

    def _location(self, place_line):
        return _parse_moka_card(_card("岗位", "发布于 2026-10-01", "全职", "全职", "|", place_line, place_line))[0]

    def test_written_when_no_city_is_lost(self):
        for line in ("内蒙古·包头市 辽宁·沈阳市", "哥伦比亚 厄瓜多尔", "上海市·黄浦区 上海市·徐汇区", "山西 山西·大同市"):
            with self.subTest(line=line):
                self.assertEqual(self._location(line), line)

    def test_written_when_cleaning_keeps_every_listed_city(self):
        # 2026-10-11 前清洗会把这些行整行折成一个城市，所以当时不写；现在逐个城市都留着。
        for line, stored in (("吉林·长春市 辽宁·沈阳市", "长春/沈阳市"),
                             ("上海市 广东·深圳市 北京市", "上海/深圳/北京"),
                             ("陕西·西安市 广东·深圳市 江苏·南京市", "西安/深圳/南京"),
                             ("上海市 广东·深圳市", "上海/深圳"),
                             ("中国香港 新加坡 山东·青岛市", "香港/新加坡/青岛"),
                             ("Hong Kong Shenzhen, Guangdong", "香港/深圳"),
                             ("Beijing, Shanghai", "北京/上海")):
            with self.subTest(line=line):
                self.assertEqual(self._location(line), line)
                self.assertEqual(normalizer.clean_location(line), stored)

    def test_foreign_or_nation_only_place_does_not_block_the_listed_cities(self):
        # 同日全集 38 张卡是「国内城市 + 中国 / 境外国家」：location 列只给国内城市用（国家只有一个，中国优先），
        # 境外那一头库里本来就表示不了。行里的国内城市一个不少就写——12 字以内的这类行改前也一直是这么写的。
        for line, stored in (("广东·深圳市 中国", "深圳"), ("马来西亚 福建·福州市", "福州"), ("印度 英国 上海市", "上海"),
                             ("海外其他 广东·深圳市", "深圳"), ("陕西·西安市 泰国 广东·深圳市", "西安/深圳"),
                             ("上海市 广东·深圳市 中国", "上海/深圳")):
            with self.subTest(line=line):
                self.assertEqual(self._location(line), line)
                self.assertEqual(normalizer.clean_location(line), stored)

    def test_not_written_when_cleaning_would_lose_a_listed_city(self):
        # 清洗把「牡丹江市·西安区」折成西安（折错的存量问题，见 normalizer.clean_location）：这时沈阳、牡丹江都不在结果里。
        line = "黑龙江·牡丹江市·西安区 辽宁·沈阳市"
        self.assertTrue(_moka_places(line), "它是地点字段，只是不能写")
        self.assertEqual(normalizer.clean_location(line), "西安")
        self.assertIsNone(self._location(line))

    def test_truncated_list_is_never_written(self):
        # 「等N个地点」只列了前 3 个：没列出来的那几个城市的用户会被硬拒，哪怕列出来的 3 个清洗不折叠。
        for line in ("湖北·黄石市 湖北·十堰市 湖北·宜昌市等8个地点", "科特迪瓦 尼日利亚 阿尔及利亚等10个地点",
                     "中国香港  新加坡  山东·青岛市  等13个地点"):
            with self.subTest(line=line):
                self.assertTrue(_moka_places(line), "它是地点字段，只是不能写")
                self.assertIsNone(self._location(line))


class MokaTitleTest(unittest.TestCase):
    """角标与标题：角标不是标题，标题自己的第一个字不是角标。"""

    def test_title_keeps_its_own_first_character_on_new_layout_cards(self):
        for title in ("热管理工程师", "新媒体运营", "新能源汽车销售", "急诊科护士"):
            with self.subTest(title=title):
                card = _card(title, "发布于 2026-10-01", "全职", "全职", "|", "上海市", "上海市")
                self.assertEqual(_parse_moka_card(card), ("上海市", title))
                marked_without_date = _card(title, "硬件", "硬件", "|", "广东·深圳市", "广东·深圳市")
                self.assertEqual(_parse_moka_card(marked_without_date)[1], title)

    def test_badge_on_its_own_line_is_dropped_and_the_title_is_left_alone(self):
        card = _card("急", "急聘服装销售", "发布于 2026-09-23", "全职", "全职", "|", "云南·昆明市", "云南·昆明市")
        self.assertEqual(_parse_moka_card(card), ("云南·昆明市", "急聘服装销售"))

    def test_unknown_badge_text_is_recognised_by_the_date_line_position(self):
        # 标题后面紧跟发布日期；第三行才是发布日期 → 第一行是角标，不管它写的是什么。
        card = _card("Top", "品牌创意实习生", "发布于 2026-05-21", "上海市", "上海市")
        self.assertEqual(_parse_moka_card(card), ("上海市", "品牌创意实习生"))
        self.assertEqual(_split_moka_title(["仿真", "发布于 2026-05-21", "上海市", "上海市"])[0], "仿真")

    def test_old_layout_strips_only_the_glued_ji_badge(self):
        self.assertEqual(_parse_moka_card(_card("急客户端c++研发", "全职技术类", "广东·珠海市", "发布时间：2026-05-20")),
                         ("广东·珠海市", "客户端c++研发"))
        self.assertEqual(_parse_moka_card(_card("新零售运营管培生", "销售服务部运营类", "广东·广州市", "发布时间：2023-10-27")),
                         ("广东·广州市", "新零售运营管培生"))
        self.assertEqual(_parse_moka_card(_card("热线客服", "其它", "发布时间：2019-04-29")), (None, "热线客服"))

    def test_title_only_link_from_the_old_layout_sidebar(self):
        self.assertEqual(_parse_moka_card("急行业经理"), (None, "行业经理"))


class MokaLocationEndToEndTest(unittest.TestCase):
    """解析结果过完入库清洗之后的样子——用户看到的、筛选读到的是这个。"""

    def test_department_no_longer_reaches_the_location_column(self):
        self.assertEqual(_normalized("dept-region-before-location")["location"], "天津市")
        self.assertEqual(_normalized("category-market-before-location")["location"], "上海")

    def test_overseas_region_category_no_longer_flips_a_hangzhou_job_overseas(self):
        row = _normalized("category-overseas-region-before-location")
        self.assertEqual((row["location"], row["country_code"], row["job_scope"]), ("杭州", "CN", "domestic"))

    def test_foreign_country_is_overseas_instead_of_domestic_by_default(self):
        row = _normalized("foreign-country")
        self.assertEqual((row["country_code"], row["job_scope"]), ("ID", "overseas"))
        self.assertEqual(_normalized("multi-place-foreign-complete")["job_scope"], "overseas")

    def test_lossless_multi_place_line_keeps_every_city(self):
        self.assertEqual(_normalized("multi-place-kept-when-cleaning-is-lossless")["location"],
                         "内蒙古·包头市 辽宁·沈阳市")

    def test_multi_place_line_keeps_every_city_after_cleaning(self):
        # 2026-10-11 前清洗把「吉林·长春市 辽宁·沈阳市」折成「长春」（沈阳的用户看不到），当时只能不写、保持城市未知。
        row = _normalized("multi-place-with-alias-city-kept")
        self.assertEqual((row["location"], row["country_code"], row["job_scope"]), ("长春/沈阳市", "CN", "domestic"))
        self.assertEqual(_normalized("multi-place-three-cities-kept")["location"], "上海/深圳/北京")
        self.assertEqual(_normalized("multi-place-short-line-kept")["location"], "上海/深圳")
        self.assertEqual(_normalized("english-two-places-kept")["location"], "香港/深圳")

    def test_nation_only_stays_unknown(self):
        row = _normalized("nation-only-is-not-a-location")
        self.assertIsNone(row["location"])
        self.assertEqual(row["job_scope"], "domestic")

    def test_english_portal_location_becomes_the_city(self):
        self.assertEqual(_normalized("english-city-province")["location"], "深圳")

    def test_title_survives_normalisation_with_its_first_character(self):
        self.assertEqual(_normalized("title-starts-with-re-new-layout")["title"], "热管理工程师")
        self.assertEqual(_normalized("badge-english-own-line")["title"], "品牌创意实习生")


class _SidebarPage:
    """列表 + 右栏「最新职位」。右栏每页都在、只有标题；它里面的岗在列表里排在第 2 页（也是最后一页）。"""

    FULL = "急\n法务顾问\n发布于 2026-08-31\n全职\n全职\n|\n上海市\n上海市"

    def __init__(self):
        self.idx = 0

    def eval_on_selector_all(self, sel, js):
        sidebar = [{"href": "#/job/late", "text": "急\n法务顾问"}]
        if self.idx == 0:
            return [{"href": f"#/job/{i}", "text": f"岗位{i}\n发布于 2026-10-01"} for i in range(30)] + sidebar
        return [{"href": "#/job/late", "text": self.FULL}] + sidebar

    def query_selector_all(self, sel):
        return [_PageNo("1"), _PageNo("2")]

    def query_selector(self, sel):
        return None if "好的" in sel else _SidebarNext(self)

    def wait_for_timeout(self, _ms):
        pass


class _PageNo:
    def __init__(self, text):
        self._text = text

    def inner_text(self):
        return self._text


class _SidebarNext:
    def __init__(self, page):
        self.page = page

    def get_attribute(self, name):
        last = self.page.idx >= 1
        if name == "class":
            return "sd-Pagination-forward disabled" if last else "sd-Pagination-forward"
        return "" if (name == "disabled" and last) else None

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def click(self, timeout=None):
        self.page.idx += 1


class MokaSidebarShadowTest(unittest.TestCase):
    def test_full_card_replaces_the_title_only_sidebar_link(self):
        """同一个岗先从右栏收到（只有标题），翻到它所在的页后要换成完整卡片，否则地点字段就丢了。"""
        adapter = MokaAdapter()
        cards = adapter._collect_all_pages(_SidebarPage())
        by_href = {c["href"]: c["text"] for c in cards}
        self.assertEqual(len(cards), 31)
        self.assertEqual(by_href["#/job/late"], _SidebarPage.FULL)
        self.assertEqual(_parse_moka_card(by_href["#/job/late"]), ("上海市", "法务顾问"))

    def test_page_whose_only_job_was_already_seen_in_the_sidebar_still_counts(self):
        """末页唯一的岗早在右栏里见过：没有「新增」，但换成了完整卡片 = 确实翻到了这一页，不能报成没抓全。"""
        adapter = MokaAdapter()
        cards = adapter._collect_all_pages(_SidebarPage())
        adapter._finalize_coverage(cards, "https://app.mokahr.com/social-recruitment/t/1")
        self.assertEqual(adapter._pages_done, 2)
        self.assertTrue(adapter.fetch_complete)


if __name__ == "__main__":
    unittest.main()
