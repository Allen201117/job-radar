"""Wikidata 解析纯逻辑单测（不打网络；HTTP 编排在 CI live 跑）。"""
import unittest

import wikidata as W


def _item(qid):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}


def _str(s):
    return {"mainsnak": {"datavalue": {"value": s}}}


def _time(t):
    return {"mainsnak": {"datavalue": {"value": {"time": t}}}}


def _qty(amount, year=None):
    c = {"mainsnak": {"datavalue": {"value": {"amount": amount}}}}
    if year:
        c["qualifiers"] = {"P585": [{"datavalue": {"value": {"time": f"+{year}-00-00T00:00:00Z"}}}]}
    return c


LISTED_ENTITY = {
    "id": "Q123",
    "labels": {"zh": {"value": "测试集团"}},
    "claims": {
        "P31": [_item("Q891723")],          # public company
        "P414": [_item("Q739514")],         # HKEX → 港交所
        "P249": [_str("9988")],
        "P571": [_time("+2014-04-00T00:00:00Z")],
        "P1128": [_qty("+250000", "2023"), _qty("+100000", "2018")],
        "P159": [_item("Q8686")],
        "P452": [_item("Q9999")],
    },
}
LABEL_MAP = {"Q8686": "上海", "Q9999": "电子商务", "Q739514": "港交所"}

PRIVATE_ENTITY = {
    "id": "Q456",
    "labels": {"zh": {"value": "某未上市公司"}},
    "claims": {"P571": [_time("+2012-00-00T00:00:00Z")]},
}


class TestWikidataParse(unittest.TestCase):
    def test_parse_listed_company(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        self.assertEqual(f["label"], "测试集团")
        self.assertTrue(f["listed"])
        self.assertEqual(f["exchanges"], ["港交所"])
        self.assertEqual(f["ticker"], "9988")
        self.assertEqual(f["founded_year"], 2014)
        self.assertEqual(f["employees"], 250000)        # 取 point-in-time 最新（2023）
        self.assertEqual(f["headcount_band"], "10万+")
        self.assertEqual(f["hq"], "上海")
        self.assertEqual(f["industry"], "电子商务")
        self.assertIn("Q8686", f["_ref_qids"])

    def test_headcount_band(self):
        self.assertEqual(W.headcount_band(250000), "10万+")
        self.assertEqual(W.headcount_band(3000), "1000-5000")
        self.assertEqual(W.headcount_band(80), "1-100")
        self.assertIsNone(W.headcount_band(None))
        self.assertIsNone(W.headcount_band(0))

    def test_facts_to_listing_listed(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        li = W.facts_to_listing(f)
        self.assertEqual(li["dimension"], "listing")
        self.assertEqual(li["grade"], "fact")
        self.assertEqual(li["origin"], "wikidata")
        self.assertEqual(li["payload"]["status"], "listed")
        self.assertIn("已上市", li["content"])
        self.assertIn("港交所", li["content"])
        self.assertIn("9988", li["content"])
        self.assertTrue(li["source_url"].startswith("https://www.wikidata.org/wiki/Q123"))

    def test_facts_to_listing_private(self):
        f = W.parse_company_facts(PRIVATE_ENTITY, {})
        li = W.facts_to_listing(f)
        self.assertEqual(li["payload"]["status"], "private")
        self.assertIn("未", li["content"])

    def test_facts_to_profile(self):
        f = W.parse_company_facts(LISTED_ENTITY, LABEL_MAP)
        p = W.facts_to_profile(f)
        self.assertEqual(p["founded_year"], 2014)
        self.assertEqual(p["headcount_band"], "10万+")
        self.assertEqual(p["hq_location"], "上海")
        self.assertEqual(p["funding_stage"], "已上市")

    def test_no_signal_returns_none(self):
        empty = {"id": "Q0", "labels": {"en": {"value": "Nothing"}}, "claims": {}}
        f = W.parse_company_facts(empty, {})
        self.assertIsNone(W.facts_to_listing(f))


class TestNameVariants(unittest.TestCase):
    """公司名降解：库里存实体全称，Wikidata 收品牌短名（2026-09-17 live 实测 16/25 因此查无）。"""

    def test_original_name_always_first(self):
        self.assertEqual(W.name_variants("雅迪科技集团")[0], "雅迪科技集团")

    def test_strips_legal_suffix(self):
        self.assertIn("盐津铺子食品", W.name_variants("盐津铺子食品股份有限公司"))
        self.assertIn("雅迪", W.name_variants("雅迪科技集团"))

    def test_brand_in_parentheses_kept_region_dropped(self):
        got = W.name_variants("天玺（北京）文化科技有限公司（万代南梦宫）")
        self.assertIn("万代南梦宫", got)          # 括号里的品牌名要留
        self.assertNotIn("北京", got)             # 括号里的注册地不是品牌

    def test_recruit_suffix_dropped(self):
        self.assertIn("云尖信息", W.name_variants("云尖信息 实习"))

    def test_short_ascii_fragment_never_split_off(self):
        """live 实测：「陶氏化学 Dow」拆出的 `Dow` 命中美国国防部（别名 DOW）。"""
        self.assertNotIn("Dow", W.name_variants("陶氏化学 Dow"))
        self.assertIn("安克创新", W.name_variants("安克创新 Anker"))
        self.assertIn("Anker", W.name_variants("安克创新 Anker"))  # ≥5 字符才拆

    def test_no_empty_or_dupe(self):
        got = W.name_variants("TCL")
        self.assertEqual(got, ["TCL"])
        self.assertEqual(W.name_variants("  "), [])


class TestPlausibleCompanyHit(unittest.TestCase):
    def _hit(self, label, mtype="label", text=None, aliases=None):
        return {"id": "Q1", "label": label,
                "match": {"type": mtype, "text": text if text is not None else label},
                "aliases": aliases}

    def test_exact_label_accepted(self):
        self.assertTrue(W.plausible_company_hit("雅迪", self._hit("雅迪")))

    def test_legal_suffix_difference_tolerated_both_sides(self):
        self.assertTrue(W.plausible_company_hit("国家电网", self._hit("国家电网公司")))

    def test_containment_rejected(self):
        """`京东` ⊂ `京东方` 是立过碑的红线：包含一律不算命中。"""
        self.assertFalse(W.plausible_company_hit("京东", self._hit("京东方")))
        self.assertFalse(W.plausible_company_hit("京东方", self._hit("京东")))

    def test_short_ascii_alias_rejected(self):
        """`DOW` 是美国国防部的别名、`Tcl` 是编程语言 —— 短西文名只认正式标签。"""
        hit = self._hit("United States Department of Defense", mtype="alias",
                        text="DOW", aliases=["DOW"])
        self.assertFalse(W.plausible_company_hit("Dow", hit))

    def test_long_name_alias_still_accepted(self):
        hit = self._hit("China First Heavy Industries", mtype="alias", text="中国一重",
                        aliases=["中国一重"])
        self.assertTrue(W.plausible_company_hit("中国一重", hit))


class TestIsCompanyEntity(unittest.TestCase):
    def test_human_rejected_even_with_org_props(self):
        ent = {"claims": {"P31": [_item("Q5")], "P159": [_str("x")]}}
        self.assertFalse(W.is_company_entity(ent))

    def test_org_instance_of_accepted(self):
        self.assertTrue(W.is_company_entity({"claims": {"P31": [_item("Q4830453")]}}))

    def test_org_only_property_accepted_when_p31_unknown(self):
        """白名单不可能全，靠「组织专属属性」兜底（人/概念/编程语言都不会有 P452）。"""
        self.assertTrue(W.is_company_entity({"claims": {"P31": [_item("Q999999")],
                                                        "P452": [_item("Q11661")]}}))

    def test_concept_rejected(self):
        self.assertFalse(W.is_company_entity({"claims": {"P31": [_item("Q151885")]}}))
        self.assertFalse(W.is_company_entity({}))
        self.assertFalse(W.is_company_entity(None))


if __name__ == "__main__":
    unittest.main()
