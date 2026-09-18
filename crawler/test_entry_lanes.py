"""五条入口车道的离线单测：候选产出 / 逐车道退避 / 台账计数。全部注入依赖，不打网络。"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import campus_hints
import entry_lanes as EL
import slug_variants


NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)


class LaneOrderTest(unittest.TestCase):
    def test_search_is_the_last_resort(self):
        """创始人 2026-09-18 定的硬约束：搜索额度只能是最后手段。
        往前挪任何一条车道之前，先算清它花的是什么。"""
        self.assertEqual(EL.LANE_ORDER[-1], EL.LANE_SEARCH)
        self.assertEqual(
            EL.LANE_ORDER,
            (EL.LANE_SLUG, EL.LANE_HOMEPAGE, EL.LANE_HINT, EL.LANE_IGUOPIN, EL.LANE_SEARCH),
        )

    def test_every_lane_has_its_own_backoff_window(self):
        for lane in EL.LANE_ORDER:
            self.assertIn(lane, EL.LANE_RETRY_DAYS)


class LaneBackoffTest(unittest.TestCase):
    def test_one_failed_lane_does_not_block_the_others(self):
        """「退避锁死自我修复」那块碑：一条车道失败只许锁自己。"""
        ledger = EL.record_lane({}, EL.LANE_SLUG, found=False, company="甲公司", now=NOW)
        row = {"evidence": {"lanes": ledger}}
        planned = EL.plan_lanes(row, now=NOW)
        self.assertNotIn(EL.LANE_SLUG, planned)
        self.assertIn(EL.LANE_HOMEPAGE, planned)
        self.assertIn(EL.LANE_HINT, planned)

    def test_backoff_expires(self):
        ledger = EL.record_lane({}, EL.LANE_HINT, found=False, company="甲公司", now=NOW)
        later = NOW + timedelta(days=EL.LANE_RETRY_DAYS[EL.LANE_HINT] * 2)
        self.assertIn(EL.LANE_HINT, EL.plan_lanes({"evidence": {"lanes": ledger}}, now=later))

    def test_found_lane_clears_its_backoff(self):
        ledger = EL.record_lane({}, EL.LANE_SLUG, found=True, company="甲公司", now=NOW)
        self.assertIsNone(ledger[EL.LANE_SLUG]["next_retry_at"])
        self.assertIn(EL.LANE_SLUG, EL.plan_lanes({"evidence": {"lanes": ledger}}, now=NOW))

    def test_search_lane_never_sets_its_own_backoff(self):
        """搜索车道的节流归 entry_finder 的公司级 next_retry_at 管；
        这里再设一个会出现两套互相打架的节流。"""
        ledger = EL.record_lane({}, EL.LANE_SEARCH, found=False, company="甲公司", now=NOW)
        self.assertIsNone(ledger[EL.LANE_SEARCH]["next_retry_at"])

    def test_unreadable_timestamp_fails_open(self):
        ledger = {EL.LANE_SLUG: {"next_retry_at": "不是时间"}}
        self.assertFalse(EL.lane_blocked(ledger, EL.LANE_SLUG, NOW))

    def test_backoff_is_spread_not_all_on_one_day(self):
        days = {
            EL.record_lane({}, EL.LANE_SLUG, found=False, company=name, now=NOW)
            [EL.LANE_SLUG]["next_retry_at"][:10]
            for name in ("甲公司", "乙公司", "丙公司", "丁公司", "戊公司")
        }
        self.assertGreater(len(days), 1, "固定天数退避会让同批失败的公司全挤在同一天")

    def test_record_lane_does_not_mutate_the_input(self):
        original = {}
        EL.record_lane(original, EL.LANE_SLUG, found=False, company="甲", now=NOW)
        self.assertEqual(original, {})


class SlugLaneTest(unittest.TestCase):
    def test_only_verified_hits_become_candidates(self):
        """张冠李戴门不可旁路：discover_domestic 判 verified=False 的命中一律不进候选。"""
        hits = [
            {"platform": "feishu", "verified": False, "url": "https://x.jobs.feishu.cn/index/position"},
            {"platform": "moka", "verified": True, "url": "https://app.mokahr.com/social-recruitment/y/1"},
        ]
        urls = [item["url"] for item in EL.hit_candidates(hits)]
        self.assertEqual(urls, ["https://app.mokahr.com/social-recruitment/y/1"])

    def test_wecruit_hit_expands_only_channels_with_jobs(self):
        hits = [{
            "platform": "wecruit", "verified": True,
            "origin": "https://acme.hotjob.cn", "suite_key": "SU123",
            "channels": [("social.html", 2, 12), ("school.html", 1, 0)],
        }]
        urls = [item["url"] for item in EL.hit_candidates(hits)]
        self.assertEqual(urls, ["https://acme.hotjob.cn/SU123/pb/social.html"])

    def test_candidates_carry_preset_so_spa_shells_are_not_identity_rejected(self):
        hits = [{"platform": "moka", "verified": True, "slug_hit": "acmehr",
                 "url": "https://app.mokahr.com/social-recruitment/acmehr/1"}]
        preset = EL.hit_candidates(hits)[0]["preset"]
        self.assertEqual(preset["adapter"], "moka")
        self.assertTrue(preset["identity_ok"])
        self.assertIn("title_verified", preset["identity_reason"])

    def test_probe_exception_never_takes_down_the_company(self):
        def boom(_target, _platforms):
            raise RuntimeError("网络炸了")
        self.assertEqual(
            EL.slug_candidates("甲公司", variant_fn=lambda *_a, **_k: ["jia"],
                               platform_probe=boom),
            [],
        )

    def test_no_variants_means_no_probe_at_all(self):
        calls = []
        EL.slug_candidates("甲", variant_fn=lambda *_a, **_k: [],
                           platform_probe=lambda *a: calls.append(a) or [])
        self.assertEqual(calls, [])


class HomepageLaneTest(unittest.TestCase):
    def test_returns_links_and_entry_channel(self):
        items, site = EL.homepage_candidates(
            "甲公司",
            site_resolver=lambda _c: {"home_url": "https://jia.com/",
                                      "entry_channel": "verified_domain_table"},
            link_finder=lambda _c, _h: [{"url": "https://jia.com/careers", "score": 200}],
        )
        self.assertEqual([item["url"] for item in items], ["https://jia.com/careers"])
        self.assertEqual(site["entry_channel"], "verified_domain_table")
        self.assertEqual(items[0]["lane"], EL.LANE_HOMEPAGE)

    def test_resolver_failure_is_not_fatal(self):
        def boom(_c):
            raise RuntimeError("wikidata down")
        self.assertEqual(EL.homepage_candidates("甲", site_resolver=boom,
                                                link_finder=lambda *_a: []), ([], None))


class HintLaneTest(unittest.TestCase):
    def test_third_party_platforms_are_dropped(self):
        rows = [{"company": "甲公司", "campus_url_hint": "https://www.zhipin.com/job/1"}]
        self.assertEqual(campus_hints.hints_from_targets(rows), {})

    def test_official_hint_is_kept_for_both_names(self):
        rows = [{"company": "帆软", "cn": "帆软科技", "campus_url_hint": "https://join.fanruan.com"}]
        table = campus_hints.hints_from_targets(rows)
        self.assertEqual(table["帆软"], "https://join.fanruan.com")
        self.assertEqual(table["帆软科技"], "https://join.fanruan.com")

    def test_lookup_is_exact_match_only(self):
        """🚫 子串匹配会让「京东」直接吃到「京东方」的网申链接 —— 张冠李戴红线。"""
        table = {"京东方": "https://boe.example/campus"}
        self.assertIsNone(campus_hints.hint_for("京东", hints=table))
        self.assertEqual(campus_hints.hint_for("京东方", hints=table),
                         "https://boe.example/campus")

    def test_hint_candidate_has_no_preset(self):
        """线索未经任何核验 → 必须照常过页面身份门，不许给 preset 抄近路。"""
        items = EL.hint_candidates("帆软", hints={"帆软": "https://join.fanruan.com"})
        self.assertEqual(items[0]["url"], "https://join.fanruan.com")
        self.assertNotIn("preset", items[0])

    def test_real_targets_file_parses(self):
        table = campus_hints.load_hints(campus_hints.TARGETS_FILE)
        self.assertGreater(len(table), 20, "targets_campus_2027.json 的 hint 字段应能读出来")
        for url in table.values():
            self.assertTrue(campus_hints.is_allowed_hint(url))


class IguopinLaneTest(unittest.TestCase):
    def test_not_indexed_means_no_candidate(self):
        """不能给每家都拼一条国聘候选：那会让国聘变成所有公司的兜底入口。"""
        self.assertEqual(EL.iguopin_candidates("某民企", indexed=lambda _n: False), [])

    def test_indexed_company_gets_the_company_scoped_url(self):
        items = EL.iguopin_candidates("中国核工业集团", indexed=lambda _n: True)
        self.assertEqual(len(items), 1)
        self.assertIn("iguopin.com/job?company=", items[0]["url"])
        self.assertEqual(items[0]["preset"]["adapter"], "iguopin")

    def test_index_lookup_requires_a_name_match_not_just_a_hit(self):
        """国聘的搜索是**集团级模糊匹配**（84% 挂错公司的老坑）——
        「搜得到」不等于「是这家」，必须过 company_name_match。"""
        class _Cli:
            def post(self, *_a, **_k):
                return _Body({"code": 200, "data": {"list": [
                    {"company_name": "屯昌县劳动就业服务中心"}]}})

            def close(self):
                pass

        class _Body:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        self.assertFalse(EL.iguopin_indexed("华润集团", client=_Cli()))

    def test_index_lookup_accepts_a_real_subsidiary_name(self):
        class _Body:
            def json(self):
                return {"code": 200, "data": {"list": [
                    {"company_name": "华润集团有限公司"}]}}

        class _Cli:
            def post(self, *_a, **_k):
                return _Body()

            def close(self):
                pass

        self.assertTrue(EL.iguopin_indexed("华润集团", client=_Cli()))

    def test_network_failure_is_silent(self):
        class _Cli:
            def post(self, *_a, **_k):
                raise RuntimeError("down")

            def close(self):
                pass

        self.assertFalse(EL.iguopin_indexed("甲公司", client=_Cli()))


class SlugVariantTest(unittest.TestCase):
    def test_latin_name_yields_deterministic_variants(self):
        got = slug_variants.deterministic_variants("Acme Technology Co., Ltd")
        self.assertIn("acme", got)
        self.assertIn("acmehr", got)

    def test_seeds_come_first(self):
        got = slug_variants.deterministic_variants("Acme", seeds=["acmecorp"])
        self.assertEqual(got[0], "acmecorp")

    def test_illegal_slugs_are_dropped(self):
        self.assertIsNone(slug_variants.normalize_slug("acme.hotjob.cn/x"))
        self.assertIsNone(slug_variants.normalize_slug(""))
        self.assertEqual(slug_variants.normalize_slug("ACME-HR"), "acme-hr")

    def test_llm_slugs_are_merged_and_capped(self):
        got = slug_variants.variants(
            "比亚迪", seeds=["byd"],
            chat=lambda _m: {"slugs": ["biyadi", "byd-hr", "BYD", "不合法的 slug"] + [
                "x%d" % i for i in range(20)]},
            budget=lambda *_a, **_k: True,
        )
        self.assertEqual(got[0], "byd")
        self.assertIn("biyadi", got)
        self.assertLessEqual(len(got), slug_variants.MAX_VARIANTS)

    def test_budget_denied_falls_back_to_deterministic(self):
        calls = []
        got = slug_variants.variants("比亚迪", seeds=["byd"],
                                     chat=lambda m: calls.append(m) or {"slugs": ["x"]},
                                     budget=lambda *_a, **_k: False)
        self.assertEqual(calls, [])
        self.assertIn("byd", got)

    def test_llm_failure_falls_back_to_deterministic(self):
        def boom(_m):
            raise RuntimeError("siliconflow down")
        got = slug_variants.variants("比亚迪", seeds=["byd"], chat=boom,
                                     budget=lambda *_a, **_k: True)
        self.assertIn("byd", got)

    def test_garbage_llm_payload_is_ignored(self):
        self.assertEqual(slug_variants.parse_llm_slugs({"slugs": "notalist"}), [])
        self.assertEqual(slug_variants.parse_llm_slugs(None), [])

    def test_prompt_mentions_the_noise_stripped_core_name(self):
        text = slug_variants.build_messages("比亚迪股份有限公司")[-1]["content"]
        self.assertIn("比亚迪", text)


class LaneMetricsTest(unittest.TestCase):
    def test_all_lane_keys_exist_even_at_zero(self):
        """零产出必须看得见：缺键会被读成「这条车道没跑」。"""
        counts = EL.summarize_lanes([])
        for lane in EL.LANE_ORDER:
            self.assertEqual(counts["found_by_%s" % lane], 0)
        self.assertEqual(counts["not_found"], 0)

    def test_counts_by_lane_and_not_found(self):
        counts = EL.summarize_lanes([
            {"evidence": {"entry_lane": EL.LANE_SLUG}},
            {"evidence": {"entry_lane": EL.LANE_SLUG}},
            {"evidence": {"entry_lane": EL.LANE_SEARCH}},
            {"evidence": {}},
            {"evidence": {"entry_lane": "不认识的车道"}},
        ])
        self.assertEqual(counts["found_by_slug"], 2)
        self.assertEqual(counts["found_by_search"], 1)
        self.assertEqual(counts["not_found"], 2)
        self.assertEqual(sum(counts.values()), 5, "计数必须守恒")


if __name__ == "__main__":
    unittest.main()
