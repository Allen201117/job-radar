"""一个 Moka 门户发多家公司的岗时，按岗位卡上写的部门逐行归属（不打真网络）。

病例（2026-10-14 live）：租户 vanke 的默认社招门户 36266（万科官网「社会招聘」）里，挂在「物业事业部」
（部门编号 671608）下的岗是万物云的，旧代码每条都贴 sources.company=万科企业。
判据与取舍见 adapters/china_ats.py 的 _MOKA_DEPT_SHARED_PORTALS 注释。
夹具是同日门户全量岗位卡上的部门（status-item）与「页面自己的部门筛选取回来的物业事业部全集」这份真值。
"""
import html
import json
import os
import unittest
from collections import Counter

import normalizer
from adapters import china_ats
from adapters.china_ats import (MokaAdapter, moka_card_department_verdict, moka_department_owners,
                                moka_department_tree, moka_dept_shared_portal, moka_shared_portal_verdict)

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures",
                        "moka_vanke_social_departments.json")
with open(_FIXTURE, encoding="utf-8") as _f:
    FIXTURE = json.load(_f)

PORTAL = FIXTURE["portal"]
HOME, OTHER = FIXTURE["home"], FIXTURE["other"]
REGISTRY = china_ats._MOKA_DEPT_SHARED_PORTALS["vanke/36266"]


def _doc(init_data):
    """门户主文档里那一行 <input id="init-data" value="…HTML 转义的 JSON…">。"""
    return f'<html><input type="hidden" id="init-data" value="{html.escape(json.dumps(init_data, ensure_ascii=False))}"></html>'


TREE = moka_department_tree(_doc(FIXTURE["init_data"]))
BY_LABEL = moka_department_owners(REGISTRY, TREE)


def _card(title, tags, date="2026-10-10", n=0):
    return {"href": f"#/job/{n:08d}-aaaa-bbbb-cccc-000000000000",
            "text": f"{title}\n{''.join(tags)}\n安徽·合肥市\n发布时间：{date}", "tags": list(tags)}


def _payload(cards, base=PORTAL, tree=TREE):
    data = {"_base": base, "cards": cards}
    if tree is not None:
        data["_departments"] = tree
    return json.dumps(data, ensure_ascii=False)


class RegistryTest(unittest.TestCase):
    def test_only_this_one_portal_is_registered(self):
        self.assertEqual(sorted(china_ats._MOKA_DEPT_SHARED_PORTALS), ["vanke/36266"])

    def test_registry_entries_are_well_formed(self):
        for key, portal in china_ats._MOKA_DEPT_SHARED_PORTALS.items():
            self.assertEqual(key, key.lower())
            self.assertNotIn(key, china_ats._MOKA_SHARED_PORTALS, "一个门户只能用一种判法")
            self.assertTrue(portal["owners"])
            self.assertTrue(all(isinstance(n, int) and not isinstance(n, bool) for n in portal["owners"]), key)
            self.assertTrue(portal["home_company"].strip())
            self.assertNotIn(portal["home_company"], portal["owners"].values(), key)

    def test_lookup_by_portal_page_or_job_link(self):
        self.assertIs(moka_dept_shared_portal(PORTAL), REGISTRY)
        self.assertIs(moka_dept_shared_portal(PORTAL + "#/job/76e7a1d6-809d-4648-8302-bc0cbb64417c"), REGISTRY)
        self.assertIs(moka_dept_shared_portal("https://app.mokahr.com/apply/vanke/36266#/"), REGISTRY)
        for url in ("https://app.mokahr.com/apply/vanke/37205", "https://app.mokahr.com/campus-recruitment/vanke/147055",
                    PORTAL + "1", "", None):
            self.assertIsNone(moka_dept_shared_portal(url), url)

    def test_home_company_matches_fixture(self):
        self.assertEqual(REGISTRY["home_company"], HOME)
        self.assertEqual(REGISTRY["owners"], {FIXTURE["registered_node"]: OTHER})


class DepartmentTreeTest(unittest.TestCase):
    def test_reads_groups_and_parents_from_the_real_document(self):
        groups = FIXTURE["init_data"]["jobsGroupedByDepartment"]
        nodes = FIXTURE["init_data"]["departmentsStructure"]
        self.assertEqual(TREE["groups"], [[g["id"], g["label"]] for g in groups])
        self.assertEqual(TREE["parents"], [[n["id"], n["parentId"]] for n in nodes])

    def test_either_attribute_order_of_the_input(self):
        """value 写在 id 前面的写法同样认（与读门户总数同一组正则）。"""
        escaped = html.escape(json.dumps(FIXTURE["init_data"], ensure_ascii=False))
        self.assertEqual(moka_department_tree(f'<input value="{escaped}" id="init-data">'), TREE)

    def test_missing_or_malformed_is_none_not_a_guess(self):
        data = FIXTURE["init_data"]
        for doc in ("", None, "<html>当前网页已关停</html>", '<input id="init-data" value="{not json">',
                    _doc({"jobStats": {"total": 3}}),
                    _doc({"jobsGroupedByDepartment": data["jobsGroupedByDepartment"]}),
                    _doc({"departmentsStructure": data["departmentsStructure"]}),
                    _doc({"jobsGroupedByDepartment": [{"id": "1", "label": "x"}], "departmentsStructure": []}),
                    _doc({"jobsGroupedByDepartment": [{"id": 1}], "departmentsStructure": []}),
                    _doc({"jobsGroupedByDepartment": [], "departmentsStructure": [{"id": 1, "parentId": "2"}]}),
                    _doc({"jobsGroupedByDepartment": [], "departmentsStructure": [{"id": True, "parentId": None}]})):
            self.assertIsNone(moka_department_tree(doc), doc)


class DepartmentOwnersTest(unittest.TestCase):
    def test_real_groups_split_by_the_registered_node(self):
        """物业事业部下 13 组归万物云，其余 23 组（地区公司 / 事业部 / 集团总部 / 挂在根上的「万科集团」）归本家。"""
        self.assertEqual(len(BY_LABEL), len(FIXTURE["init_data"]["jobsGroupedByDepartment"]))
        tally = Counter(BY_LABEL.values())
        self.assertEqual(tally, Counter({OTHER: 13, "": 23}))
        self.assertEqual(BY_LABEL["万科物业-50942330"], OTHER)
        self.assertEqual(BY_LABEL["万御安防-50919596"], OTHER)
        self.assertEqual(BY_LABEL["万科集团"], "")
        self.assertEqual(BY_LABEL["华中公司"], "")
        self.assertEqual(BY_LABEL["集团总部"], "")

    def test_group_counts_on_each_side_add_up_to_portal_groups(self):
        groups = {g["label"]: g["jobCount"] for g in FIXTURE["init_data"]["jobsGroupedByDepartment"]}
        by_side = Counter()
        for label, n in groups.items():
            by_side[BY_LABEL[label] or HOME] += n
        self.assertEqual(dict(by_side), FIXTURE["group_totals"])

    def test_registered_node_missing_from_tree_is_an_error(self):
        tree = {"groups": [[1, "a"]], "parents": [[1, None]]}
        with self.assertRaises(ValueError) as ctx:
            moka_department_owners(REGISTRY, tree)
        self.assertIn("671608", str(ctx.exception))

    def test_unresolvable_groups_are_left_out(self):
        portal = {"owners": {10: "别家"}, "home_company": "本家"}
        tree = {"groups": [[11, "别家组"], [21, "本家组"], [99, "不在树里"], [31, "上级不在树里"], [41, "成环"],
                           [12, "同名"], [22, "同名"], [13, "同名同归属"], [14, "同名同归属"]],
                "parents": [[10, 1], [1, None], [11, 10], [21, 1], [31, 77], [41, 42], [42, 41],
                            [12, 10], [22, 1], [13, 10], [14, 10]]}
        self.assertEqual(moka_department_owners(portal, tree),
                         {"别家组": "别家", "本家组": "", "同名同归属": "别家"})

    def test_registered_node_itself_can_be_a_group(self):
        portal = {"owners": {10: "别家"}, "home_company": "本家"}
        tree = {"groups": [[10, "直属"]], "parents": [[10, 1], [1, None]]}
        self.assertEqual(moka_department_owners(portal, tree), {"直属": "别家"})


class CardVerdictTest(unittest.TestCase):
    def test_department_plus_function_tags(self):
        self.assertEqual(moka_card_department_verdict(BY_LABEL, ["万物云本部-50907939", "安全"]), (OTHER, True))
        self.assertEqual(moka_card_department_verdict(BY_LABEL, ["物流事业部", "财务"]), (None, True))
        self.assertEqual(moka_card_department_verdict(BY_LABEL, [" 万科物业-50942330 "]), (OTHER, True))

    def test_unknown_or_ambiguous_cards(self):
        for tags in ([], None, ["安全"], ["物业事业部", "安全"], ["万科物业-50942330", "物流事业部"], [None, 3]):
            self.assertEqual(moka_card_department_verdict(BY_LABEL, tags), (None, False), tags)

    def test_department_must_be_the_first_tag(self):
        """部门是第一个 status-item。第一个不是分组名（部门没渲染出来、只剩职能）就判不了，
        不去后面的标签里找——职能名碰巧等于某个分组名时那样会静默判错。"""
        self.assertEqual(moka_card_department_verdict(BY_LABEL, ["安全", "万科物业-50942330"]), (None, False))
        self.assertEqual(moka_card_department_verdict(BY_LABEL, ["万科物业-50942330", "万科物业-50942330"]),
                         (OTHER, True))

    def test_title_is_not_used(self):
        """标题以另一个分组名开头（「华中公司（武汉）-建筑设计岗」）也只看卡上的部门。"""
        jobs = MokaAdapter().parse(_payload([_card("华中公司（武汉）-建筑设计岗", ["万科物业-50942330", "设计"])]))
        self.assertEqual(jobs[0].company, OTHER)


class FullPortalReplayTest(unittest.TestCase):
    """2026-10-14 门户全量逐张回放：卡上部门判出来的归属必须等于页面部门筛选给的真值，两个方向都是 0。"""

    def test_every_real_card(self):
        cases = FIXTURE["cases"]
        total = sum(n for *_x, n in cases)
        self.assertEqual(total, FIXTURE["cards_total"])
        self.assertGreater(total, 1300, "夹具被改小了？下面的循环会空转着通过")
        tally = Counter()
        for tags, truth, n in cases:
            owner, known = moka_card_department_verdict(BY_LABEL, tags)
            got = owner or HOME
            tally[(truth, got, known)] += n
            with self.subTest(tags=tags):
                self.assertTrue(known)
                self.assertEqual(got, truth)
        self.assertEqual({k: v for k, v in tally.items()},
                         {(OTHER, OTHER, True): FIXTURE["truth_totals"][OTHER],
                          (HOME, HOME, True): FIXTURE["truth_totals"][HOME]})

    def test_cards_per_group_equal_portal_job_counts(self):
        """卡上的部门就是 jobsGroupedByDepartment 的分组：每组张数等于门户自报。"""
        per_label = Counter()
        for tags, _truth, n in FIXTURE["cases"]:
            (label,) = [t for t in tags if t in BY_LABEL]
            per_label[label] += n
        self.assertEqual(dict(per_label),
                         {g["label"]: g["jobCount"] for g in FIXTURE["init_data"]["jobsGroupedByDepartment"]})


class ParseTest(unittest.TestCase):
    def test_real_cards_get_per_row_company_and_parse_otherwise_unchanged(self):
        samples = FIXTURE["samples"]
        adapter = MokaAdapter()
        adapter._today = lambda: china_ats.date(2026, 10, 14)
        shared = adapter.parse(_payload(samples))
        plain = adapter.parse(json.dumps({"_base": "https://app.mokahr.com/social-recruitment/vanke/1",
                                          "cards": samples}, ensure_ascii=False))
        self.assertEqual(len(shared), len(samples))
        self.assertEqual([(j.title, j.location, j.posted_at) for j in shared],
                         [(j.title, j.location, j.posted_at) for j in plain])
        self.assertEqual([j.company for j in plain], [""] * len(samples))
        want = [OTHER if BY_LABEL[[t for t in s["tags"] if t in BY_LABEL][0]] else "" for s in samples]
        self.assertEqual([j.company for j in shared], want)
        self.assertIn(OTHER, want)
        self.assertIn("", want)

    def test_normalize_keeps_row_company_over_source_company(self):
        jobs = MokaAdapter().parse(_payload([_card("安全员-合肥战区", ["万物云本部-50907939", "安全"], n=1),
                                             _card("财务岗", ["物流事业部", "财务"], n=2)]))
        out = {j.title: normalizer.normalize(j, source_id="s", company=HOME)["company"] for j in jobs}
        self.assertEqual(out, {"安全员-合肥战区": OTHER, "财务岗": HOME})

    def test_too_old_cards_are_not_counted_for_the_guard(self):
        """超出年限口径的卡先被筛掉，不进「认不出」的分母。"""
        cards = [_card("老岗", [], date="2019-01-01", n=1), _card("老岗二", [], date="2019-01-01", n=2),
                 _card("新岗", ["万科物业-50942330", "客服"], n=3)]
        adapter = MokaAdapter()
        jobs = adapter.parse(_payload(cards))
        self.assertEqual([(j.title, j.company) for j in jobs], [("新岗", OTHER)])
        self.assertEqual(len(adapter.retire_jd_urls), 2)

    def test_other_portals_ignore_tags_and_departments(self):
        for base in ("https://app.mokahr.com/apply/vanke/37205", "https://app.mokahr.com/social-recruitment/vanke/1"):
            jobs = MokaAdapter().parse(_payload([_card("安全员", ["万物云本部-50907939", "安全"])], base=base))
            self.assertEqual(jobs[0].company, "", base)

    def test_title_registry_is_untouched(self):
        self.assertEqual(moka_shared_portal_verdict(PORTAL, "万象生-推广岗（商业-厦门)"), (None, True))


class GuardTest(unittest.TestCase):
    def test_missing_tree_with_cards_is_failure(self):
        with self.assertRaises(RuntimeError) as ctx:
            MokaAdapter().parse(_payload([_card("安全员", ["万物云本部-50907939", "安全"])], tree=None))
        self.assertIn("部门树", str(ctx.exception))
        self.assertIn("vanke/36266", str(ctx.exception))

    def test_registered_node_gone_is_failure(self):
        tree = {"groups": TREE["groups"], "parents": [p for p in TREE["parents"] if p[0] != 671608]}
        with self.assertRaises(RuntimeError) as ctx:
            MokaAdapter().parse(_payload([_card("安全员", ["万物云本部-50907939", "安全"])], tree=tree))
        self.assertIn("671608", str(ctx.exception))

    def test_empty_portal_needs_no_tree(self):
        self.assertEqual(MokaAdapter().parse(_payload([], tree=None)), [])

    def test_majority_unknown_is_failure(self):
        """卡片读不到部门了（门户改版 / 选择器失效）：照常入库会把万物云的岗整批贴回万科。"""
        cards = [_card("安全员", [], n=1), _card("管家", ["客服"], n=2), _card("财务岗", ["物流事业部", "财务"], n=3)]
        with self.assertRaises(RuntimeError) as ctx:
            MokaAdapter().parse(_payload(cards))
        self.assertIn("3 个岗里 2 个认不出部门", str(ctx.exception))

    def test_some_unknown_rows_fall_back_home_and_are_named(self):
        cards = [_card("安全员", ["万物云本部-50907939", "安全"], n=1), _card("财务岗", ["物流事业部", "财务"], n=2),
                 _card("新部门的岗", ["新开的部门", "安全"], n=3)]
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            jobs = MokaAdapter().parse(_payload(cards))
        self.assertEqual([j.company for j in jobs], [OTHER, "", ""])
        self.assertTrue(any("新部门的岗" in line and "新开的部门" in line and "1/3" in line for line in logs.output))

    def test_all_known_rows_log_nothing(self):
        with self.assertNoLogs("adapters.china_ats", level="WARNING"):
            MokaAdapter().parse(_payload([_card("安全员", ["万物云本部-50907939", "安全"], n=1),
                                          _card("财务岗", ["物流事业部", "财务"], n=2)]))

    def test_no_group_under_registered_node_warns(self):
        """登记的节点还在树里，却没有一个分组挂在它下面（树被改平了也是这个样子）：照常入库，但要告警。"""
        tree = {"groups": [[g, label] for g, label in TREE["groups"] if BY_LABEL[label] == ""],
                "parents": TREE["parents"]}
        with self.assertLogs("adapters.china_ats", level="WARNING") as logs:
            jobs = MokaAdapter().parse(_payload([_card("财务岗", ["物流事业部", "财务"])], tree=tree))
        self.assertEqual([j.company for j in jobs], [""])
        self.assertTrue(any("没有一个分组挂在登记的节点下" in line for line in logs.output))


class _Resp:
    def __init__(self, body=None, error=None):
        self._body, self._error = body, error

    def text(self):
        if self._error:
            raise self._error
        return self._body


class FetchPlumbingTest(unittest.TestCase):
    DOC = _doc({**FIXTURE["init_data"], "jobStats": {"total": 1313}})

    def _adapter(self, base=PORTAL, list_filter=""):
        a = MokaAdapter()
        a._own_base = base
        a._list_filter = list_filter
        a._plan_dept_portal(base)
        return a

    def test_registered_portal_reads_tags_and_tree(self):
        a = self._adapter()
        self.assertIn("status-item-", a._cards_js)
        a._note_portal_total(_Resp(self.DOC), PORTAL + "#/jobs")
        self.assertEqual(a._portal_total, 1313)
        self.assertEqual(a._dept_tree, TREE)

    def test_other_portals_keep_the_old_card_script_and_skip_the_tree(self):
        base = "https://app.mokahr.com/social-recruitment/vanke/1"
        a = self._adapter(base)
        self.assertEqual(a._cards_js, MokaAdapter._cards_js)
        self.assertNotIn("status-item-", a._cards_js)
        a._note_portal_total(_Resp(self.DOC), base + "#/jobs")
        self.assertEqual(a._portal_total, 1313)
        self.assertIsNone(a._dept_tree)

    def test_planning_resets_between_sources(self):
        """同一个 adapter 实例先抓登记的门户、再抓别的源：读卡脚本和部门树都要回到默认。"""
        a = self._adapter()
        a._note_portal_total(_Resp(self.DOC), PORTAL + "#/jobs")
        a._plan_dept_portal("https://app.mokahr.com/social-recruitment/vanke/1")
        self.assertIsNone(a._dept_tree)
        self.assertEqual(a._cards_js, MokaAdapter._cards_js)

    def test_filtered_registered_portal_still_reads_the_tree_but_not_the_total(self):
        a = self._adapter(list_filter="#/jobs?zhineng=1")
        a._note_portal_total(_Resp(self.DOC), PORTAL + "#/jobs?zhineng=1")
        self.assertIsNone(a._portal_total)
        self.assertEqual(a._dept_tree, TREE)

    def test_other_document_and_unreadable_body(self):
        a = self._adapter()
        a._note_portal_total(_Resp(self.DOC), "https://app.mokahr.com/campus_apply/vanke/999#/jobs")
        self.assertIsNone(a._dept_tree)
        with self.assertLogs("adapters.china_ats", level="WARNING"):
            a._note_portal_total(_Resp(error=RuntimeError("No resource with given identifier")), PORTAL)
        self.assertIsNone(a._dept_tree)


class ReattributeScriptTest(unittest.TestCase):
    def test_script_refuses_department_portals(self):
        import contextlib
        import io

        import reattribute_moka_shared_portal as script
        err = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
            script.parse_args(["--url-prefix", PORTAL])
        self.assertIn("下一轮重抓", err.getvalue())


if __name__ == "__main__":
    unittest.main()
