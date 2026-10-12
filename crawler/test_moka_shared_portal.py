"""一个 Moka 门户发多家公司的岗时，按标题末尾的业务段逐行归属（不打真网络）。

病例（2026-10-12 live）：租户 crland 的校招门户 168540（「华润置地2027届秋招」）自报 441 个岗，
372 个的部门挂在「华润万象生活」节点下，旧代码每条都贴 sources.company=华润置地。
判据与取舍见 adapters/china_ats.py 的 _MOKA_SHARED_PORTALS 注释；夹具是同日的全量岗位与部门真值。
"""
import json
import os
import unittest
from collections import Counter

import normalizer
from adapters import china_ats
from adapters.china_ats import (MokaAdapter, moka_portal_key, moka_shared_portal,
                                moka_shared_portal_verdict, moka_title_segment)

PORTAL = "https://app.mokahr.com/campus-recruitment/crland/168540"
SOCIAL = "https://app.mokahr.com/social-recruitment/crland/143066"
WXSH = "华润万象生活"
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "moka_crland_campus_titles.json")

with open(_FIXTURE, encoding="utf-8") as _f:
    FIXTURE = json.load(_f)


def _payload(titles, base=PORTAL):
    cards = [{"href": f"#/job/{i:08d}-aaaa-bbbb-cccc-000000000000",
              "text": f"{t}\n广东·深圳市\n广东·深圳市\n岗位职责：……"} for i, t in enumerate(titles)]
    return json.dumps({"_base": base, "cards": cards}, ensure_ascii=False)


class PortalKeyTest(unittest.TestCase):
    def test_portal_page_and_job_link_share_one_key(self):
        self.assertEqual(moka_portal_key(PORTAL), "crland/168540")
        self.assertEqual(moka_portal_key(PORTAL + "#/job/3e467d42-a27c-4507-bbcf-a20f356f7306"), "crland/168540")
        self.assertEqual(moka_portal_key("https://app.mokahr.com/campus_apply/crland/168540#/jobs"), "crland/168540")

    def test_key_ignores_case_like_the_watchdog_portal_identity(self):
        """源地址大小写写得不一样时，不能悄悄变成「不是共享门户」。"""
        import ops_watchdog
        for url in (PORTAL, PORTAL.replace("crland", "CRLand"), PORTAL.replace("https://app", "HTTPS://APP")):
            self.assertEqual(moka_portal_key(url), "crland/168540", url)
        self.assertEqual(moka_portal_key(PORTAL), ops_watchdog.portal_identity(PORTAL))

    def test_longer_portal_number_is_another_portal(self):
        self.assertEqual(moka_portal_key(PORTAL + "1"), "crland/1685401")
        self.assertNotIn(moka_portal_key(PORTAL + "1"), china_ats._MOKA_SHARED_PORTALS)

    def test_portal_number_must_end_where_the_number_ends(self):
        """门户号后面粘着别的字符的不是这个门户（不能截出前面那串数字来认）。"""
        for tail in ("a", "-2", "_x"):
            self.assertEqual(moka_portal_key(PORTAL + tail), "", tail)
        for tail in ("/", "#/jobs", "?a=1", "/jobs"):
            self.assertEqual(moka_portal_key(PORTAL + tail), "crland/168540", tail)

    def test_not_a_moka_portal(self):
        for url in ("", None, "https://app.mokahr.com/", "https://chinalife.zhiye.com/custom/intern",
                    "https://app.mokahr.com/campus-recruitment/crland"):
            self.assertEqual(moka_portal_key(url), "", url)


class TitleSegmentTest(unittest.TestCase):
    def test_segment_is_text_before_dash_in_trailing_brackets(self):
        for title, want in (
            ("万象生-推广岗（商业-厦门)", "商业"),          # 全角开、半角关，门户上就是这么写的
            ("百匠新人-土建工程岗(开发-北京)", "开发"),
            ("万象生-物业岗(商业-石家庄)", "商业"),        # 岗位名里的「物业」不算，只看末尾括号
            ("万象生-战略管理岗（万象生活总部）", "万象生活总部"),
            ("万悦生-运营管理岗(酒管-成都) ", "酒管"),
            ("百匠新人-人力资源岗(武汉)", "武汉"),
        ):
            self.assertEqual(moka_title_segment(title), want, title)

    def test_no_trailing_brackets_means_no_segment(self):
        for title in ("", None, "招商运营岗", "招商运营岗（商业）-厦门", "（商业-厦门)招商运营岗"):
            self.assertEqual(moka_title_segment(title), "", title)

    def test_nested_brackets_are_not_guessed(self):
        """括号套括号时分不清哪一段是业务段：不取。"""
        for title in ("招商运营岗（商业（厦门））", "招商运营岗(商业(A)-厦门)"):
            self.assertEqual(moka_title_segment(title), "", title)


class VerdictTest(unittest.TestCase):
    def test_wanxiang_segments_go_to_wanxiang(self):
        for title in ("万象生-推广岗（商业-厦门)", "万悦生-客户服务岗（物业-重庆)", "百匠新人-招商运营岗（商业）",
                      "万象生-写字楼运营岗(写字楼-深圳)", "万象生-战略管理岗(万象生活总部)"):
            self.assertEqual(moka_shared_portal_verdict(PORTAL, title), (WXSH, True), title)

    def test_crland_own_segments_stay_home_and_count_as_known(self):
        for title in ("百匠新人-土建工程岗(开发-北京)", "万象生-活动管理岗（文体-厦门)",
                      "百匠新人-投资管理岗(有巢-南京)", "万悦生-市场销售岗(酒管-成都)"):
            self.assertEqual(moka_shared_portal_verdict(PORTAL, title), (None, True), title)

    def test_unknown_segment_stays_home_but_is_flagged(self):
        """认不出的不猜：留在门户本家，但要让调用方知道这一行没判出来。"""
        for title in ("百匠新人-人力资源岗(武汉)", "管培生", "万象生-推广岗", "百匠新人-运营岗（商业地产-深圳)",
                      "百匠新人-运营岗（商-业）"):
            self.assertEqual(moka_shared_portal_verdict(PORTAL, title), (None, False), title)

    def test_brand_prefix_is_not_the_rule(self):
        """同一个校招品牌两边都有：只看末尾的业务段。"""
        self.assertEqual(moka_shared_portal_verdict(PORTAL, "百匠新人-招商运营岗（商业-深圳)")[0], WXSH)
        self.assertIsNone(moka_shared_portal_verdict(PORTAL, "百匠新人-投资管理岗(开发-深圳)")[0])
        self.assertEqual(moka_shared_portal_verdict(PORTAL, "万悦生-客户服务岗（物业-重庆)")[0], WXSH)
        self.assertIsNone(moka_shared_portal_verdict(PORTAL, "万悦生-运营管理岗(酒管-杭州)")[0])

    def test_unregistered_portals_are_untouched(self):
        title = "万象生-推广岗（商业-厦门)"
        for url in (SOCIAL, PORTAL + "1", "https://app.mokahr.com/campus-recruitment/crland/143067",
                    "https://app.mokahr.com/campus-recruitment/vanke/168540", "", None):
            self.assertEqual(moka_shared_portal_verdict(url, title), (None, True), url)

    def test_only_this_one_portal_is_registered(self):
        self.assertEqual(sorted(china_ats._MOKA_SHARED_PORTALS), ["crland/168540"])

    def test_registry_entries_are_well_formed(self):
        """一个业务段不能同时登记给别家和本家（那样别家会悄悄赢）；本家不能出现在别家名单里；键必须是小写。"""
        for key, portal in china_ats._MOKA_SHARED_PORTALS.items():
            self.assertEqual(key, key.lower())
            self.assertFalse(set(portal["owners"]) & set(portal["home_segments"]), key)
            self.assertTrue(portal["home_company"].strip())
            self.assertNotIn(portal["home_company"], portal["owners"].values(), key)
            self.assertTrue(all(seg == seg.strip() and seg for seg in [*portal["owners"], *portal["home_segments"]]))

    def test_shared_portal_lookup(self):
        self.assertEqual(moka_shared_portal(PORTAL + "#/job/x")["home_company"], "华润置地")
        self.assertEqual(moka_shared_portal(PORTAL)["home_company"], FIXTURE["home"])
        self.assertIsNone(moka_shared_portal(SOCIAL))
        self.assertIsNone(moka_shared_portal(""))


class FullPortalReplayTest(unittest.TestCase):
    """2026-10-12 门户全量 441 个岗逐个回放：标题判出来的归属必须等于部门真值，两个方向都是 0。"""

    def test_every_real_job(self):
        cases = FIXTURE["cases"]
        self.assertEqual(sum(n for *_x, n in cases), FIXTURE["total"])
        self.assertEqual(FIXTURE["total"], 441, "夹具被改小了？下面的循环会空转着通过")
        tally = Counter()
        for title, department, truth, n in cases:
            owner, known = moka_shared_portal_verdict(PORTAL, title)
            got = owner or FIXTURE["home"]
            tally[(truth, got, known)] += n
            with self.subTest(title=title, department=department):
                self.assertEqual(got, truth)
                self.assertTrue(known)
        self.assertEqual(dict(tally), {(WXSH, WXSH, True): 372, ("华润置地", "华润置地", True): 69})

    def test_by_department_class_matches_portal_groups(self):
        """按部门大类逐类对上门户自报的分组：商业大区 213 / 物业 111 / 万象生活本部 36 / 万象城 12；
        开发航道 34 / 文化体育 23 / 有巢 7 / 酒店管理 5。"""
        def klass(department):
            if department.startswith("商业") and "大区" in department:
                return "商业大区"
            for prefix in ("物业", "华润万象生活", "开发航道", "文化体育公司", "有巢", "酒店管理公司"):
                if department.startswith(prefix):
                    return prefix
            return "万象城" if department.endswith("万象城") else department

        by_class = Counter()
        for title, department, _truth, n in FIXTURE["cases"]:
            owner, _known = moka_shared_portal_verdict(PORTAL, title)
            by_class[(klass(department), owner or FIXTURE["home"])] += n
        self.assertEqual(dict(by_class), {
            ("商业大区", WXSH): 213, ("物业", WXSH): 111, ("华润万象生活", WXSH): 36, ("万象城", WXSH): 12,
            ("开发航道", "华润置地"): 34, ("文化体育公司", "华润置地"): 23,
            ("有巢", "华润置地"): 7, ("酒店管理公司", "华润置地"): 5,
        })


class ParseTest(unittest.TestCase):
    def test_parse_sets_company_per_row(self):
        jobs = MokaAdapter().parse(_payload([
            "万象生-推广岗（商业-厦门)", "百匠新人-土建工程岗(开发-北京)",
            "万悦生-客户服务岗（物业-重庆)", "万悦生-运营管理岗(酒管-杭州)"]))
        self.assertEqual({j.title: j.company for j in jobs}, {
            "万象生-推广岗（商业-厦门)": WXSH,
            "百匠新人-土建工程岗(开发-北京)": "",        # 空 = normalize 用 sources.company 兜底
            "万悦生-客户服务岗（物业-重庆)": WXSH,
            "万悦生-运营管理岗(酒管-杭州)": "",
        })
        self.assertTrue(all(j.jd_url.startswith(PORTAL + "#/job/") for j in jobs))

    def test_normalize_keeps_row_company_over_source_company(self):
        jobs = MokaAdapter().parse(_payload(["万象生-推广岗（商业-厦门)", "百匠新人-土建工程岗(开发-北京)"]))
        out = {j.title: normalizer.normalize(j, source_id="s", company="华润置地")["company"] for j in jobs}
        self.assertEqual(out, {"万象生-推广岗（商业-厦门)": WXSH, "百匠新人-土建工程岗(开发-北京)": "华润置地"})

    def test_title_survives_normalize_with_its_segment(self):
        """存量重归属按库里的标题判：入库清洗不许把末尾的业务段弄丢。"""
        for title, _department, truth, _n in FIXTURE["cases"]:
            raw = MokaAdapter().parse(_payload([title]))[0]
            stored = normalizer.normalize(raw, source_id="s", company="华润置地")
            owner, known = moka_shared_portal_verdict(stored["jd_url"], stored["title"])
            self.assertEqual((owner or "华润置地", known), (truth, True), title)

    def test_other_portals_parse_exactly_as_before(self):
        titles = ["万象生-推广岗（商业-厦门)", "招商运营岗", "百匠新人-人力资源岗(武汉)"]
        for base in (SOCIAL, "https://app.mokahr.com/campus-recruitment/vanke/1", PORTAL + "1"):
            with self.assertNoLogs("adapters.china_ats", level="WARNING"):
                jobs = MokaAdapter().parse(_payload(titles, base=base))
            self.assertEqual([j.company for j in jobs], ["", "", ""], base)
            self.assertEqual([j.title for j in jobs], titles, base)

    def test_adapter_company_name_still_fills_home_rows(self):
        adapter = MokaAdapter()
        adapter.company_name = "华润置地"
        jobs = adapter.parse(_payload(["万象生-推广岗（商业-厦门)", "百匠新人-土建工程岗(开发-北京)"]))
        self.assertEqual([j.company for j in jobs], [WXSH, "华润置地"])


class GuardTest(unittest.TestCase):
    def test_no_recognisable_segment_at_all_is_failure_not_silent_fallback(self):
        """标题写法整体变了：照常入库 = 把全部岗悄悄贴回 sources.company，必须记失败。"""
        with self.assertRaises(RuntimeError) as ctx:
            MokaAdapter().parse(_payload(["万象生-推广岗-厦门", "百匠新人-土建工程岗-北京", "管培生"]))
        self.assertIn("crland/168540", str(ctx.exception))

    def test_majority_unknown_is_failure_too(self):
        """新发的岗换了写法、老的还认得：过半认不出就不写，否则库里已经归到别家的岗会被悄悄贴回本家。"""
        with self.assertRaises(RuntimeError) as ctx:
            MokaAdapter().parse(_payload(["万象生-推广岗（商业·厦门）", "万象生-营运岗（商业·天津）",
                                          "百匠新人-土建工程岗(开发-北京)"]))
        self.assertIn("3 个岗里 2 个认不出", str(ctx.exception))

    def test_some_unknown_rows_fall_back_home_and_are_named_in_the_log(self):
        """个别认不出（不过半）：留在本家、照常入库，日志里点名。"""
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            jobs = MokaAdapter().parse(_payload(["万象生-推广岗（商业-厦门)", "百匠新人-人力资源岗(武汉)"]))
        self.assertEqual({j.title: j.company for j in jobs},
                         {"万象生-推广岗（商业-厦门)": WXSH, "百匠新人-人力资源岗(武汉)": ""})
        self.assertTrue(any("百匠新人-人力资源岗(武汉)" in line and "1/2" in line for line in logs.output))

    def test_guard_does_not_apply_to_other_portals(self):
        jobs = MokaAdapter().parse(_payload(["管培生", "招商运营岗"], base=SOCIAL))
        self.assertEqual(len(jobs), 2)

    def test_all_known_rows_log_nothing(self):
        with self.assertNoLogs("adapters.china_ats", level="WARNING"):
            MokaAdapter().parse(_payload(["万象生-推广岗（商业-厦门)", "百匠新人-土建工程岗(开发-北京)"]))

    def test_only_home_rows_left_is_fine(self):
        """万象生活的岗先招完、只剩置地自己的岗：不是故障。"""
        jobs = MokaAdapter().parse(_payload(["百匠新人-土建工程岗(开发-北京)", "万悦生-运营管理岗(酒管-杭州)"]))
        self.assertEqual([j.company for j in jobs], ["", ""])

    def test_empty_portal_is_fine(self):
        self.assertEqual(MokaAdapter().parse(_payload([])), [])


if __name__ == "__main__":
    unittest.main()
