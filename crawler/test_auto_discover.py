"""auto_discover 定向扩源选目标/选入库 纯函数单测（不打真网络、不连库）。

红线：① 只 probe 库里没有的目标(不重复劳动) ② 用户点名的优先 ③ 只入库 source_url 不在库的(去重)
④ 每日上限封顶(不一夜铺量)。
"""
import unittest

import auto_discover as ad


def _t(company, slugs=None):
    return {"company": company, "cn": company, "slugs": slugs or [company.lower()], "industry": "x"}


class PlanTargetsTest(unittest.TestCase):
    def test_filters_out_existing_companies(self):
        curated = [_t("比亚迪"), _t("美团"), _t("立讯精密")]
        out = ad.plan_targets(curated, set(), {"美团"}, cap=10, seed=1)
        names = [t["company"] for t in out]
        self.assertNotIn("美团", names)            # 已在库 → 不重复 probe
        self.assertIn("比亚迪", names)
        self.assertIn("立讯精密", names)

    def test_filters_out_existing_companies_by_normalized_name(self):
        curated = [_t("美图公司"), _t("得物")]
        out = ad.plan_targets(curated, set(), {"美图"}, cap=10, seed=1)
        names = [t["company"] for t in out]
        self.assertNotIn("美图公司", names)        # 后缀变体已在库 → 不重复 probe
        self.assertEqual(names, ["得物"])

    def test_user_wanted_first(self):
        curated = [_t("A"), _t("B"), _t("C"), _t("D")]
        out = ad.plan_targets(curated, {"C"}, set(), cap=10, seed=7)
        self.assertEqual(out[0]["company"], "C")    # 用户点名的排最前

    def test_cap_limits_batch(self):
        curated = [_t(f"C{i}") for i in range(50)]
        out = ad.plan_targets(curated, set(), set(), cap=12, seed=3)
        self.assertEqual(len(out), 12)              # 每日封顶

    def test_seed_rotation_deterministic_but_varies(self):
        curated = [_t(f"C{i}") for i in range(40)]
        a = [t["company"] for t in ad.plan_targets(curated, set(), set(), cap=10, seed=1)]
        a2 = [t["company"] for t in ad.plan_targets(curated, set(), set(), cap=10, seed=1)]
        b = [t["company"] for t in ad.plan_targets(curated, set(), set(), cap=10, seed=2)]
        self.assertEqual(a, a2)                     # 同 seed 同结果（可复现）
        self.assertNotEqual(a, b)                   # 不同 seed 轮转覆盖不同批

    def test_skips_blank_company(self):
        out = ad.plan_targets([{"company": ""}, _t("X")], set(), set(), cap=10, seed=0)
        self.assertEqual([t["company"] for t in out], ["X"])

    def test_priority_targets_before_rest(self):
        # 科技/新经济/消费(_priority) 排在传统清单之前（对齐目标用户，别被制造业淹没）
        curated = [_t("Old1"), _t("Old2"), {**_t("Tech1"), "_priority": True},
                   {**_t("Tech2"), "_priority": True}]
        out = [t["company"] for t in ad.plan_targets(curated, set(), set(), cap=10, seed=5)]
        self.assertLess(max(out.index("Tech1"), out.index("Tech2")),
                        min(out.index("Old1"), out.index("Old2")))

    def test_user_wanted_beats_priority(self):
        curated = [{**_t("Tech1"), "_priority": True}, _t("Old1")]
        out = ad.plan_targets(curated, {"Old1"}, set(), cap=10, seed=1)
        self.assertEqual(out[0]["company"], "Old1")   # 用户点名 > 科技/消费优先清单


class CuratedTargetsFileTest(unittest.TestCase):
    def test_tech_consumer_file_loaded_and_prioritized(self):
        targets = ad.load_curated_targets()
        techs = [t for t in targets if t.get("_priority")]
        self.assertGreaterEqual(len(techs), 100)      # 科技/消费清单已并入并标优先
        for t in techs:
            self.assertTrue(t.get("company") and t.get("cn") and t.get("slugs"))
        names = [t["company"] for t in targets]
        self.assertEqual(len(names), len(set(names)))  # 跨全部清单公司名去重（不重复劳动）


class PlanInsertsTest(unittest.TestCase):
    def _p(self, company, url):
        return {"company": company, "adapter": "feishu", "url": url, "_valid": 5}

    def test_dedups_against_existing_urls(self):
        passed = [self._p("A", "https://a.com"), self._p("B", "https://b.com")]
        out = ad.plan_inserts(passed, {"https://a.com"}, cap=10)
        self.assertEqual([r["company"] for r in out], ["B"])   # a 已在库 → 跳过

    def test_dedups_within_batch(self):
        passed = [self._p("A", "https://a.com"), self._p("A2", "https://a.com")]
        out = ad.plan_inserts(passed, set(), cap=10)
        self.assertEqual(len(out), 1)               # 批内同 url 只留一条

    def test_cap_limits_inserts(self):
        passed = [self._p(f"C{i}", f"https://c{i}.com") for i in range(30)]
        out = ad.plan_inserts(passed, set(), cap=15)
        self.assertEqual(len(out), 15)

    def test_skips_blank_url(self):
        passed = [{"company": "A", "adapter": "feishu", "url": ""}, self._p("B", "https://b.com")]
        out = ad.plan_inserts(passed, set(), cap=10)
        self.assertEqual([r["company"] for r in out], ["B"])


if __name__ == "__main__":
    unittest.main()
