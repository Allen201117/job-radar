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

    def test_brand_short_name_covered_by_full_name_in_db(self):
        """清单写品牌短名、库里写全称/带英文名 → 必须判「已覆盖」，不再天天重探。

        2026-07-31 线上实测：这类假缺失让 httpx 扩源道连日「验证通过 11 / 可入库 0」——
        探活能过（因为库里真有这家），但 source_url 去重把它全挡掉，等于 100% 空烧探测名额。"""
        existing = {"隆基绿能 LONGi", "度小满金融科技（北京）有限公司", "极兔速递", "歌尔股份 GoerTek"}
        curated = [_t("隆基绿能"), _t("度小满"), _t("极兔"), _t("歌尔股份"), _t("真的新公司")]
        names = [t["company"] for t in ad.plan_targets(curated, set(), existing, cap=10, seed=1)]
        self.assertEqual(names, ["真的新公司"])

    def test_place_prefixed_full_name_in_db_covers_brand(self):
        # 库里是「地名 + 品牌」的法人全称 → 同一家，不重探（复用张冠李戴核验的归属规则）
        names = [t["company"] for t in ad.plan_targets(
            [_t("蓝色光标"), _t("双汇")], set(), {"北京蓝色光标数据科技", "河南双汇投资发展"},
            cap=10, seed=1)]
        self.assertEqual(names, [])

    def test_corporate_form_suffix_variant_is_covered(self):
        # 清单「创维集团」↔ 库里「创维 Skyworth 校招」：剥掉「集团」才是归属前缀，只比原始名会漏
        names = [t["company"] for t in ad.plan_targets(
            [_t("创维集团")], set(), {"创维 Skyworth 校招"}, cap=10, seed=1)]
        self.assertEqual(names, [])

    def test_different_company_sharing_a_token_still_probed(self):
        # 「网易」在库 ≠ 「网易有道」已覆盖；「万达集团」在库 ≠ 「万达电影」已覆盖 —— 不许误并
        names = [t["company"] for t in ad.plan_targets(
            [_t("网易有道"), _t("万达电影")], set(), {"网易", "万达集团"}, cap=10, seed=1)]
        self.assertEqual(sorted(names), ["万达电影", "网易有道"])

    def test_must_apply_tier_cannot_starve_other_tiers(self):
        """必投缺口梯队再大也不能吃满每日名额。

        2026-07-31 线上实测：必投缺口 133 家 > 每日 cap 80，严格优先级下 76/80 名额恒被它吃掉，
        priority（科技/消费 + 每天 LLM 新生成的候选）与 rest 拿到 0 —— 「持续喂清单」完全空转。"""
        curated = ([{**_t(f"M{i}"), "_must_apply": True} for i in range(200)]
                   + [{**_t(f"P{i}"), "_priority": True} for i in range(100)]
                   + [_t(f"R{i}") for i in range(500)])
        out = ad.plan_targets(curated, set(), set(), cap=80, seed=1)
        kinds = [("must" if t.get("_must_apply") else "prio" if t.get("_priority") else "rest")
                 for t in out]
        self.assertEqual(len(out), 80)
        self.assertGreater(kinds.count("prio"), 0)
        self.assertGreater(kinds.count("rest"), 0)
        self.assertLessEqual(kinds.count("must"), 40)   # 必投缺口最多占一小半

    def test_fresh_llm_candidates_probed_before_stale_static_priority(self):
        # 同为 priority：今天 LLM 新生成的（_llm）从没探过，静态清单那批已被探了几周还不出
        # → 新料必须排前面，否则混合洗牌下新料只分到零头（2026-07-31 实测 0 产出）
        curated = ([{**_t(f"S{i}"), "_priority": True} for i in range(75)]
                   + [{**_t(f"L{i}"), "_priority": True, "_llm": True} for i in range(39)])
        out = ad.plan_targets(curated, set(), set(), cap=80, seed=1)
        prio = [t["company"] for t in out if t.get("_priority")]
        self.assertEqual(len([c for c in prio if c.startswith("L")]), 39)   # 新料全被探到

    def test_unused_tier_quota_is_reallocated(self):
        # 某梯队候选不足配额时，剩余名额顺延给别的梯队——别浪费每日预算
        curated = [{**_t("M1"), "_must_apply": True}] + [_t(f"R{i}") for i in range(50)]
        out = ad.plan_targets(curated, set(), set(), cap=20, seed=1)
        self.assertEqual(len(out), 20)

    def test_user_wanted_first(self):
        curated = [_t("A"), _t("B"), _t("C"), _t("D")]
        out = ad.plan_targets(curated, {"C"}, set(), cap=10, seed=7)
        self.assertEqual(out[0]["company"], "C")    # 用户点名的排最前

    def test_large_wanted_pool_leaves_capacity_for_must_apply(self):
        """用户点名再多也只可占半数，必投梯队仍要有本轮探测名额。"""
        curated = ([{**_t(f"W{i}"), "_priority": True} for i in range(200)]
                   + [{**_t(f"M{i}"), "_must_apply": True} for i in range(200)])
        out = ad.plan_targets(
            curated, {f"W{i}" for i in range(200)}, set(), cap=80, seed=1,
        )
        self.assertLessEqual(sum(t["company"].startswith("W") for t in out), 40)
        self.assertGreater(sum(t.get("_must_apply", False) for t in out), 0)

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


class ExtractMokaSlugTest(unittest.TestCase):
    """从 moka 社招源 URL 反推校招板块探测要用的 slug（Track A2）。"""

    def test_extracts_from_social_recruitment_url(self):
        url = "https://app.mokahr.com/social-recruitment/catlhr/98098"
        self.assertEqual(ad.extract_moka_slug(url), "catlhr")

    def test_extracts_from_legacy_apply_url(self):
        url = "https://app.mokahr.com/apply/shein/2933"
        self.assertEqual(ad.extract_moka_slug(url), "shein")

    def test_non_moka_url_returns_none(self):
        self.assertIsNone(ad.extract_moka_slug("https://xxx.zhiye.com/social"))

    def test_blank_url_returns_none(self):
        self.assertIsNone(ad.extract_moka_slug(""))
        self.assertIsNone(ad.extract_moka_slug(None))


class PlanCampusGapTargetsTest(unittest.TestCase):
    """有社招无校招的必投公司专项补探队列（Track A2）——绕过 plan_targets 的整家去重。"""

    def test_moka_social_only_company_is_queued(self):
        must_apply = {"消费/零售": [{"name": "极米", "pattern": "%极米%"}]}
        sources = [{"company": "极米科技", "source_url": "https://app.mokahr.com/social-recruitment/jimi/142344",
                    "notes": "", "adapter_name": "moka", "enabled": True}]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["company"], "极米")
        self.assertEqual(out[0]["slugs"], ["jimi"])
        self.assertEqual(out[0]["industry"], "消费/零售")

    def test_company_with_existing_campus_source_not_queued(self):
        # 已有校招源（幂等）→ 不重复补，即便还有别的社招源
        must_apply = {"消费/零售": [{"name": "极米", "pattern": "%极米%"}]}
        sources = [
            {"company": "极米科技", "source_url": "https://app.mokahr.com/social-recruitment/jimi/142344",
             "notes": "", "adapter_name": "moka", "enabled": True},
            {"company": "极米科技", "source_url": "https://app.mokahr.com/campus-recruitment/jimi/150242",
             "notes": "", "adapter_name": "moka", "enabled": True},
        ]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        self.assertEqual(out, [])

    def test_campus_source_detected_via_notes_too(self):
        # URL 本身不含 campus 特征词，但 notes 标注了「校招」→ 也算已覆盖（同 lib/campus-sources.ts）
        must_apply = {"消费/零售": [{"name": "极米", "pattern": "%极米%"}]}
        sources = [
            {"company": "极米科技", "source_url": "https://app.mokahr.com/social-recruitment/jimi/142344",
             "notes": "", "adapter_name": "moka", "enabled": True},
            {"company": "极米科技", "source_url": "https://foo.example.com/list",
             "notes": "校招专区", "adapter_name": "beisen", "enabled": True},
        ]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        self.assertEqual(out, [])

    def test_company_without_any_source_not_queued(self):
        # 连社招源都没有 → 不是「补校招」范畴，属于 plan_targets 整家新探
        must_apply = {"消费/零售": [{"name": "极米", "pattern": "%极米%"}]}
        out = ad.plan_campus_gap_targets(must_apply, [], cap=10, seed=1)
        self.assertEqual(out, [])

    def test_company_with_non_moka_source_only_not_queued(self):
        # 有社招源但不是 moka（feishu/hotjob 已在 A0 摸清覆盖或不是缺口）→ 反推不出 slug，本轮跳过
        must_apply = {"金融": [{"name": "国信证券", "pattern": "%国信证券%"}]}
        sources = [{"company": "国信证券", "source_url": "https://guoxin.jobs.feishu.cn/index/position",
                    "notes": "", "adapter_name": "feishu", "enabled": True}]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        self.assertEqual(out, [])

    def test_disabled_source_ignored(self):
        must_apply = {"消费/零售": [{"name": "极米", "pattern": "%极米%"}]}
        sources = [{"company": "极米科技", "source_url": "https://app.mokahr.com/social-recruitment/jimi/142344",
                    "notes": "", "adapter_name": "moka", "enabled": False}]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        self.assertEqual(out, [])  # disabled 源不算「已有源」，视同没有，不进补校招队列（避免复活已停用源）

    def test_collapsed_industries_prioritized(self):
        must_apply = {
            "互联网/科技": [{"name": "科技甲", "pattern": "%科技甲%"}],
            "教育": [{"name": "教育乙", "pattern": "%教育乙%"}],
        }
        sources = [
            {"company": "科技甲", "source_url": "https://app.mokahr.com/social-recruitment/tech1/1",
             "notes": "", "adapter_name": "moka", "enabled": True},
            {"company": "教育乙", "source_url": "https://app.mokahr.com/social-recruitment/edu1/2",
             "notes": "", "adapter_name": "moka", "enabled": True},
        ]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=10, seed=1)
        names = [t["company"] for t in out]
        self.assertEqual(names[0], "教育乙")   # 塌陷行业（教育）排在互联网/科技之前

    def test_cap_limits_batch(self):
        must_apply = {"消费/零售": [{"name": f"C{i}", "pattern": f"%C{i}%"} for i in range(20)]}
        sources = [{"company": f"C{i}", "source_url": f"https://app.mokahr.com/social-recruitment/c{i}/1",
                   "notes": "", "adapter_name": "moka", "enabled": True} for i in range(20)]
        out = ad.plan_campus_gap_targets(must_apply, sources, cap=5, seed=1)
        self.assertEqual(len(out), 5)

    def test_seed_rotation_deterministic_but_varies(self):
        must_apply = {"消费/零售": [{"name": f"C{i}", "pattern": f"%C{i}%"} for i in range(20)]}
        sources = [{"company": f"C{i}", "source_url": f"https://app.mokahr.com/social-recruitment/c{i}/1",
                   "notes": "", "adapter_name": "moka", "enabled": True} for i in range(20)]
        a = [t["company"] for t in ad.plan_campus_gap_targets(must_apply, sources, cap=5, seed=1)]
        a2 = [t["company"] for t in ad.plan_campus_gap_targets(must_apply, sources, cap=5, seed=1)]
        b = [t["company"] for t in ad.plan_campus_gap_targets(must_apply, sources, cap=5, seed=2)]
        self.assertEqual(a, a2)
        self.assertNotEqual(a, b)


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

    def __init__(self, rows, order_log=None):
        self.rows = rows
        self.order_log = order_log if order_log is not None else []
        self._ordered = None
        self._start, self._end = 0, 999

    def select(self, *_):
        return self

    def order(self, col, desc=False):
        self._ordered = col
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        self.order_log.append(self._ordered)
        class R:
            pass
        r = R()
        page = self.rows[self._start:self._end + 1]
        r.data = page[:1000]   # PostgREST 硬顶：一次最多 1000 行
        return r


class _PagedSb:
    def __init__(self, rows):
        self.rows = rows
        self.order_log = []   # 每次 execute 用的排序键，None = 没排序

    def table(self, _name):
        return _PagedSourcesQuery(self.rows, self.order_log)


class ExistingSourceKeysPaginationTest(unittest.TestCase):
    """回归守卫：sources 超过 1000 行时 existing_source_keys 必须分页拉全量。

    2026-07-14 线上真事故：sources 涨到 1042 行，PostgREST 单次只返回前 1000 行 →
    去重集合残缺（漏掉的正是最新入库的源）→ 同一 source_url 被重复入库 15 个。
    改回不分页会让三条扩源道重新开始造重复源。"""

    def test_reads_all_rows_beyond_postgrest_1000_row_cap(self):
        rows = [{"company": f"C{i}", "source_url": f"https://x/{i}", "enabled": True}
                for i in range(1042)]
        sb = _PagedSb(rows)
        companies, urls = ad.existing_source_keys(sb)
        self.assertEqual(len(urls), 1042, "尾部 42 行被 PostgREST 截断 → 去重失效 → 重复入库")
        self.assertIn("https://x/1041", urls)
        self.assertEqual(len(companies), 1042)
        # 无稳定排序键翻页时 Postgres 不保证行序 → 会重复取同一行 + 漏掉另一行（行数对、内容不对）。
        self.assertTrue(all(k == "id" for k in sb.order_log),
                        f"每页都必须带稳定排序键，实际 {sb.order_log}")

    def test_disabled_source_does_not_mark_company_as_covered(self):
        """一家公司只有 disabled 源时，必须仍被当作「待发现」——否则永久跳过、再也找不回平台。

        2026-07-26 实测：礼来在 sources 里只有一个 disabled 源，于是每日扩源永远跳过它，
        既不重新找平台，也不会有健康岗。URL 级去重不受影响（防重复插同一行）。"""
        rows = [{"company": "礼来", "source_url": "https://x/lilly", "enabled": False},
                {"company": "海尔", "source_url": "https://x/haier", "enabled": True}]
        companies, urls = ad.existing_source_keys(_PagedSb(rows))
        self.assertNotIn("礼来", companies, "只有 disabled 源的公司不能算已覆盖")
        self.assertIn("海尔", companies)
        self.assertIn("https://x/lilly", urls, "URL 去重仍要含 disabled，避免重复插同一行")


class AutoDiscoverLedgerTest(unittest.TestCase):
    def test_static_exhaustion_records_explicit_metrics(self):
        static_targets = [_t("已在库公司")]
        ledger = mock.Mock(return_value=True)
        with mock.patch.object(ad.db, "get_supabase", return_value=object()), \
             mock.patch.object(ad, "load_user_wanted_companies", return_value=set()), \
             mock.patch.object(ad, "existing_source_keys", return_value=({"已在库公司"}, set())), \
             mock.patch.object(ad, "load_curated_targets", return_value=static_targets), \
             mock.patch.object(ad, "load_targets", return_value=static_targets), \
             mock.patch.object(ad, "plan_targets", return_value=[]), \
             mock.patch.object(ad.ops_runs, "record_ops_run", ledger):
            ad.main()
        _sb, module, metrics = ledger.call_args.args[:3]
        self.assertEqual(module, "auto_discover")
        self.assertTrue(metrics["exhausted"])
        self.assertEqual(metrics["candidates_total"], 1)
        self.assertEqual(metrics["already_in_library"], 1)
        self.assertEqual(metrics["deduped"], 0)
