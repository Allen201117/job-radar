"""probe.py 的候选清单 → 迁移这条路，飞书候选必须先过核名（2026-10-12 立）。

❌ 迁移 218 那批（外部清单 48 个飞书租户，probe.py 探活过 32 个）只验「真出岗 + jd_url 能用」，公司名原样进库。
   2026-10-11 全量普查查出其中 3 条挂错：mammotion 记成容知日新（门户自报深圳库犸科技，84 岗）、
   global-intco 记成英科医疗（门户标题「英科再生社会招聘官网」，87 岗）、tranxmart 记成千署科技（门户自报千曙科技）。
✅ 与 discover_domestic.feishu_probe 同一把尺子：公司名的核心词必须出现在门户首页自报的
   <title> / 租户名 / keywords 里；不看岗位标题，不看 meta description。
"""
import unittest
from unittest.mock import patch

import probe


def _home(title="", tenant="", keywords="", description=""):
    head = f"<title>{title}</title>" if title else ""
    return (f'<html><head>{head}<meta name="description" content="{description}">'
            f'<meta name="keywords" content="{keywords}"></head><body>'
            f'<script>window.__DATA__={{"tenant_name":"{tenant}","use_v2_detail":"true"}}</script></body></html>')


MAMMOTION = _home("加入深圳库犸科技有限公司", "深圳库犸创新科技集团有限公司",
                  "深圳库犸创新科技集团有限公司招聘, 加入深圳库犸创新科技集团有限公司")
BYTEDANCE = _home("", "ByteDance", "字节跳动招聘官网、字节跳动招聘、字节跳动社招",
                  "字节跳动在全球推出了多款有影响力的产品，包括今日头条、抖音、西瓜视频、飞书等。")
MEITU = _home("加入Pixocial 像素互联", "美图公司", "美图公司招聘, 加入美图公司")


def _cand(company, slug, **extra):
    return {"company": company, "adapter": "feishu", "industry": "综合",
            "url": f"https://{slug}.jobs.feishu.cn/index/position", **extra}


class FeishuNameGateTest(unittest.TestCase):
    def test_portal_reporting_another_company_is_rejected_with_what_it_reports(self):
        reason = probe.feishu_name_gate(_cand("容知日新", "mammotion"), fetch_home=lambda _url: MAMMOTION)
        self.assertIsNotNone(reason)
        self.assertIn("库犸", reason)

    def test_one_wrong_character_is_rejected(self):
        home = _home("加入千曙科技", "千曙科技", "千曙科技招聘, 加入千曙科技")
        self.assertIsNotNone(probe.feishu_name_gate(_cand("千署科技", "tranxmart"), fetch_home=lambda _url: home))

    def test_product_named_only_in_meta_description_is_rejected(self):
        self.assertIsNotNone(probe.feishu_name_gate(_cand("抖音", "bytedance"), fetch_home=lambda _url: BYTEDANCE))

    def test_name_found_in_tenant_name_passes_even_when_title_is_a_sub_brand(self):
        self.assertIsNone(probe.feishu_name_gate(_cand("美图公司", "meitu"), fetch_home=lambda _url: MEITU))

    def test_home_page_is_asked_at_the_tenant_root(self):
        asked = []
        probe.feishu_name_gate(_cand("美图公司", "meitu"), fetch_home=lambda url: asked.append(url) or MEITU)
        self.assertEqual(asked, ["https://meitu.jobs.feishu.cn/"])

    def test_unreadable_home_page_fails_closed(self):
        reason = probe.feishu_name_gate(_cand("美图公司", "meitu"), fetch_home=lambda _url: None)
        self.assertIsNotNone(reason)

    def test_other_adapters_are_not_gated_and_not_fetched(self):
        def boom(_url):
            raise AssertionError("不该去取首页")
        cand = {"company": "Stripe", "adapter": "greenhouse", "url": "https://boards.greenhouse.io/stripe"}
        self.assertIsNone(probe.feishu_name_gate(cand, fetch_home=boom))

    def test_whole_feishu_family_is_gated(self):
        for adapter in ("feishu", "nio_feishu", "xpeng_feishu", "horizon_feishu", "xiaomi_feishu"):
            cand = {**_cand("容知日新", "mammotion"), "adapter": adapter}
            self.assertIsNotNone(probe.feishu_name_gate(cand, fetch_home=lambda _url: MAMMOTION), adapter)

    def test_written_reason_lets_a_brand_vs_legal_name_through_without_fetching(self):
        def boom(_url):
            raise AssertionError("写明了理由就不必再取首页")
        cand = _cand("中际旭创", "zj-innolight", name_ok="苏州旭创科技是中际旭创的经营主体")
        self.assertIsNone(probe.feishu_name_gate(cand, fetch_home=boom))

    def test_blank_reason_does_not_count(self):
        cand = _cand("容知日新", "mammotion", name_ok="   ")
        self.assertIsNotNone(probe.feishu_name_gate(cand, fetch_home=lambda _url: MAMMOTION))

    def test_the_name_checked_is_the_one_that_gets_written(self):
        # 写进迁移的是 company。候选另带一个对得上的 cn 不算数 —— 拿 cn 过门、把 company 入库，等于门没关。
        cand = _cand("容知日新", "mammotion", cn="库犸科技")
        self.assertIsNotNone(probe.feishu_name_gate(cand, fetch_home=lambda _url: MAMMOTION))

    def test_family_list_matches_the_registered_feishu_adapters_and_the_weekly_audit(self):
        import audit_hotjob_attribution
        import run
        registered = {name for name in run.ADAPTERS if name == "feishu" or name.endswith("_feishu")}
        self.assertEqual(probe._FEISHU_FAMILY, registered)
        self.assertEqual(set(audit_hotjob_attribution._FEISHU_ADAPTERS), registered)


class ProbeCandidatesTest(unittest.TestCase):
    """main 的探活循环：探活出岗 ≠ 可以入迁移，核名不过的不进 passed。"""

    def test_live_but_misnamed_feishu_candidate_never_reaches_passed(self):
        cands = [_cand("容知日新", "mammotion"), _cand("美图公司", "meitu")]
        homes = {"https://mammotion.jobs.feishu.cn/": MAMMOTION, "https://meitu.jobs.feishu.cn/": MEITU}
        with patch.object(probe, "probe_one", return_value={"ok": True, "valid": 9, "china": 9, "parsed": 9}), \
             patch.object(probe, "_feishu_home_html", side_effect=homes.get):
            passed = probe.probe_candidates(cands, timeout=1)
        self.assertEqual([c["company"] for c in passed], ["美图公司"])
        self.assertEqual(passed[0]["_valid"], 9)

    def test_candidate_that_failed_the_probe_is_not_name_checked(self):
        with patch.object(probe, "probe_one", return_value={"ok": False, "valid": 0, "reason": "boom"}), \
             patch.object(probe, "_feishu_home_html", side_effect=AssertionError("探活没过就不必核名")):
            self.assertEqual(probe.probe_candidates([_cand("美图公司", "meitu")], timeout=1), [])


class EmitSqlNameReasonTest(unittest.TestCase):
    def test_written_reason_lands_in_source_notes(self):
        cand = {**_cand("中际旭创", "zj-innolight", name_ok="苏州旭创科技是中际旭创的经营主体"),
                "_valid": 83, "_china": 83}
        sql = probe.emit_sql("999_seed_probed_sources", [cand])
        self.assertIn("苏州旭创科技是中际旭创的经营主体", sql)

    def test_candidates_without_a_reason_keep_the_old_notes(self):
        cand = {**_cand("美图公司", "meitu"), "_valid": 10, "_china": 10}
        sql = probe.emit_sql("999_seed_probed_sources", [cand])
        self.assertIn("'美图公司（综合，probe live 探活 在华 10 岗）'", sql)


if __name__ == "__main__":
    unittest.main()
