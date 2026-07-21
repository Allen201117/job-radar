"""校招往年时间线自动填充：B1 结构化解析器 + B2 官方源门 单测（不打网络）。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from campus_cycle_extract import parse_cycle_claims  # noqa: E402
from official_gate import (  # noqa: E402
    is_official_grounding,
    official_hosts_from_sources,
    decide_cycle_status,
    is_entailment,
    registrable_host,
)


class ParseCycleClaimsTest(unittest.TestCase):
    def _claim(self, **kw):
        base = {
            "season": "秋招", "batch": "提前批", "event": "开放",
            "month_start": 7, "month_end": 7, "value_text": "约7月",
            "source_idx": 0, "quote": "提前批7月开放",
        }
        base.update(kw)
        return base

    def test_valid_claim_passes(self):
        out = parse_cycle_claims({"claims": [self._claim()]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["season"], "秋招")
        self.assertEqual(out[0]["month_start"], 7)

    def test_accepts_bare_list(self):
        out = parse_cycle_claims([self._claim()])
        self.assertEqual(len(out), 1)

    def test_bad_season_dropped(self):
        out = parse_cycle_claims({"claims": [self._claim(season="夏招")]})
        self.assertEqual(out, [])

    def test_bad_batch_dropped(self):
        out = parse_cycle_claims({"claims": [self._claim(batch="社招")]})
        self.assertEqual(out, [])

    def test_bad_event_dropped(self):
        out = parse_cycle_claims({"claims": [self._claim(event="面试")]})
        self.assertEqual(out, [])

    def test_month_out_of_range_dropped(self):
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(month_start=13)]}), [])
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(month_start=0)]}), [])

    def test_month_end_optional_but_validated(self):
        self.assertEqual(len(parse_cycle_claims({"claims": [self._claim(month_end=None)]})), 1)
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(month_end=99)]}), [])

    def test_missing_evidence_dropped(self):
        # 宁缺不编：没引用片段 / 没来源序号 → 丢
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(quote="")]}), [])
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(source_idx=None)]}), [])

    def test_empty_value_text_dropped(self):
        self.assertEqual(parse_cycle_claims({"claims": [self._claim(value_text="  ")]}), [])

    def test_none_and_garbage(self):
        self.assertEqual(parse_cycle_claims(None), [])
        self.assertEqual(parse_cycle_claims({}), [])
        self.assertEqual(parse_cycle_claims({"claims": ["not-a-dict", 5]}), [])


class OfficialHostsTest(unittest.TestCase):
    def test_keeps_company_own_hosts(self):
        hosts = official_hosts_from_sources([
            "https://jobs.bytedance.com/campus",
            "https://talent.baidu.com/jobs",
        ])
        self.assertIn("jobs.bytedance.com", hosts)
        self.assertIn("talent.baidu.com", hosts)

    def test_drops_shared_ats_hosts(self):
        # 共享 ATS host 不代表某一家的官方域名（张冠李戴）→ 不进官方 allowlist
        hosts = official_hosts_from_sources([
            "https://app.mokahr.com/campus-recruitment/xgimi/150242",
            "https://anker-in.jobs.feishu.cn/index/position",
            "https://brand.zhiye.com/",
        ])
        self.assertEqual(hosts, set())


class IsOfficialGroundingTest(unittest.TestCase):
    def setUp(self):
        self.official = {"jobs.bytedance.com", "talent.baidu.com"}

    def test_exact_host_matches(self):
        self.assertTrue(is_official_grounding("https://jobs.bytedance.com/campus/123", self.official))

    def test_subdomain_matches(self):
        self.assertTrue(is_official_grounding("https://www.jobs.bytedance.com/x", self.official))

    def test_third_party_not_official(self):
        self.assertFalse(is_official_grounding("https://www.nowcoder.com/discuss/123", self.official))
        self.assertFalse(is_official_grounding("https://mp.weixin.qq.com/s/abc", self.official))

    def test_empty(self):
        self.assertFalse(is_official_grounding("", self.official))
        self.assertFalse(is_official_grounding("https://x.com", set()))


class IsEntailmentTest(unittest.TestCase):
    def test_entailment_high_conf_passes(self):
        self.assertTrue(is_entailment("entailment", 0.8))
        self.assertTrue(is_entailment("entailment", 0.6))

    def test_low_conf_fails(self):
        self.assertFalse(is_entailment("entailment", 0.5))

    def test_non_entailment_fails(self):
        self.assertFalse(is_entailment("neutral", 0.99))
        self.assertFalse(is_entailment("contradiction", 0.99))

    def test_bad_conf_fails(self):
        self.assertFalse(is_entailment("entailment", None))
        self.assertFalse(is_entailment("entailment", "x"))


class DecideCycleStatusTest(unittest.TestCase):
    def test_official_autoverifies_even_single_source(self):
        # 官方招聘域名最强，单源即可发布
        st, kind, conf = decide_cycle_status(True, 1)
        self.assertEqual((st, kind, conf), ("verified", "official_notice", "high"))

    def test_two_public_sources_verify(self):
        # 选项 B：≥2 个不同公开源一致 → 发布，标「据公开信息」
        st, kind, conf = decide_cycle_status(False, 2)
        self.assertEqual((st, kind, conf), ("verified", "public_aggregate", "medium"))

    def test_single_public_source_stays_draft(self):
        # 孤证不发布（宁缺不编）
        st, kind, conf = decide_cycle_status(False, 1)
        self.assertEqual((st, kind), ("draft", "public_aggregate"))

    def test_zero_publishers_draft(self):
        st, kind, conf = decide_cycle_status(False, 0)
        self.assertEqual(st, "draft")


class RegistrableHostTest(unittest.TestCase):
    def test_strips_www_and_subdomain(self):
        self.assertEqual(registrable_host("https://www.nowcoder.com/x"), "nowcoder.com")
        self.assertEqual(registrable_host("https://zhuanlan.zhihu.com/p/1"), "zhihu.com")
        self.assertEqual(registrable_host("https://sd.huatu.com/a"), "huatu.com")


if __name__ == "__main__":
    unittest.main()
