"""auto_discover 定向扩源选目标/选入库 纯函数单测（不打真网络、不连库）。

红线：① 只 probe 库里没有的目标(不重复劳动) ② 用户点名的优先 ③ 只入库 source_url 不在库的(去重)
④ 每日上限封顶(不一夜铺量)。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

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

    def test_four_priority_tiers_are_ordered(self):
        curated = [
            _t("Rest"),
            {**_t("Priority"), "_priority": True},
            {**_t("MustApply"), "_must_apply": True},
            {**_t("Wanted"), "_must_apply": True, "_priority": True},
        ]
        out = [t["company"] for t in ad.plan_targets(curated, {"Wanted"}, set(), cap=10, seed=1)]
        self.assertEqual(out, ["Wanted", "MustApply", "Priority", "Rest"])

    def test_user_wanted_matches_by_normalized_name(self):
        # 用户写带后缀的变体、清单写简称 → 归一后仍要命中优先（旧实现全等匹配空转）
        # 注意 norm_company 只剥后缀不剥城市前缀（防误并），所以「北京字节跳动」≠「字节跳动」是预期行为
        curated = [{**_t("Tech1"), "_priority": True}, _t("字节跳动")]
        out = ad.plan_targets(curated, {"字节跳动科技公司"}, set(), cap=10, seed=1)
        self.assertEqual(out[0]["company"], "字节跳动")

    def test_user_wanted_matches_cn_field(self):
        # 清单 company 是全称、cn 是常用名，用户按常用名点名也要命中
        curated = [{**_t("Tech1"), "_priority": True},
                   {"company": "贝壳控股", "cn": "贝壳", "slugs": ["beike"], "industry": "互联网"}]
        out = ad.plan_targets(curated, {"贝壳"}, set(), cap=10, seed=1)
        self.assertEqual(out[0]["company"], "贝壳控股")


class _FakeQuery:
    def __init__(self, table):
        self.table = table
        self._update = None

    def select(self, *_):
        return self

    def in_(self, *_):
        return self

    def update(self, payload):
        self._update = payload
        return self

    def eq(self, _col, row_id):
        for r in self.table.rows:
            if r["id"] == row_id and self._update:
                r.update(self._update)
        return self

    def execute(self):
        class R:
            pass
        r = R()
        r.data = list(self.table.rows)
        return r


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows


class _FakeSb:
    def __init__(self, watch_rows):
        self.tables = {"company_watch_requests": _FakeTable(watch_rows)}

    def table(self, name):
        return _FakeQuery(self.tables[name])


class ResolveWatchRequestsTest(unittest.TestCase):
    """扩源成功 → 用户「关注公司」请求闭环回写 covered（norm_company 双侧归一匹配）。"""

    def test_marks_matching_requests_covered(self):
        sb = _FakeSb([
            {"id": "w1", "company": "字节跳动科技", "normalized_company": "bytedance", "matched_source_ids": []},
            {"id": "w2", "company": "美团", "normalized_company": "meituan", "matched_source_ids": []},
        ])
        n = ad.resolve_watch_requests(sb, "字节跳动", "src-1")
        self.assertEqual(n, 1)
        rows = sb.tables["company_watch_requests"].rows
        self.assertEqual(rows[0]["status"], "covered")
        self.assertIn("src-1", rows[0]["matched_source_ids"])
        self.assertNotIn("status", rows[1])           # 不相干请求不动

    def test_no_match_returns_zero(self):
        sb = _FakeSb([{"id": "w1", "company": "美团", "normalized_company": "美团", "matched_source_ids": []}])
        self.assertEqual(ad.resolve_watch_requests(sb, "字节跳动", "src-1"), 0)


class CuratedTargetsFileTest(unittest.TestCase):
    def test_tech_consumer_file_loaded_and_prioritized(self):
        targets = ad.load_curated_targets()
        techs = [t for t in targets if t.get("_priority")]
        self.assertGreaterEqual(len(techs), 100)      # 科技/消费清单已并入并标优先
        for t in techs:
            self.assertTrue(t.get("company") and t.get("cn") and t.get("slugs"))
        names = [t["company"] for t in targets]
        self.assertEqual(len(names), len(set(names)))  # 跨全部清单公司名去重（不重复劳动）

    def test_must_apply_targets_win_dedup_and_get_separate_marker(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "targets_must_apply.json").write_text(json.dumps([
                _t("重复公司"), _t("必投独有"),
            ], ensure_ascii=False), encoding="utf-8")
            (base / "targets_tech_consumer.json").write_text(json.dumps([
                _t("重复公司"), _t("科技独有"),
            ], ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(ad, "_CURATED_FILES",
                                   ("targets_must_apply.json", "targets_tech_consumer.json")), \
                 mock.patch.object(ad, "Path", side_effect=lambda _path: base / "auto_discover.py"):
                targets = ad.load_curated_targets()

        self.assertEqual([t["company"] for t in targets], ["重复公司", "必投独有", "科技独有"])
        self.assertTrue(targets[0].get("_must_apply"))
        self.assertTrue(targets[1].get("_must_apply"))
        self.assertNotIn("_priority", targets[0])
        self.assertTrue(targets[2].get("_priority"))


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


class _PagedSourcesQuery:
    """模拟 PostgREST：单次最多返回 1000 行，超出必须靠 range() 分页。"""

    def __init__(self, rows):
        self.rows = rows
        self._start, self._end = 0, 999

    def select(self, *_):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        class R:
            pass
        r = R()
        page = self.rows[self._start:self._end + 1]
        r.data = page[:1000]   # PostgREST 硬顶：一次最多 1000 行
        return r


class _PagedSb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _PagedSourcesQuery(self.rows)


class ExistingSourceKeysPaginationTest(unittest.TestCase):
    """回归守卫：sources 超过 1000 行时 existing_source_keys 必须分页拉全量。

    2026-07-14 线上真事故：sources 涨到 1042 行，PostgREST 单次只返回前 1000 行 →
    去重集合残缺（漏掉的正是最新入库的源）→ 同一 source_url 被重复入库 15 个。
    改回不分页会让三条扩源道重新开始造重复源。"""

    def test_reads_all_rows_beyond_postgrest_1000_row_cap(self):
        rows = [{"company": f"C{i}", "source_url": f"https://x/{i}"} for i in range(1042)]
        companies, urls = ad.existing_source_keys(_PagedSb(rows))
        self.assertEqual(len(urls), 1042, "尾部 42 行被 PostgREST 截断 → 去重失效 → 重复入库")
        self.assertIn("https://x/1041", urls)
        self.assertEqual(len(companies), 1042)
