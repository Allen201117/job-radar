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


class DecideCycleStatusTest(unittest.TestCase):
    def test_official_plus_entailment_autoverifies(self):
        st, kind, conf = decide_cycle_status("entailment", 0.8, True)
        self.assertEqual(st, "verified")
        self.assertEqual(kind, "official_notice")
        self.assertEqual(conf, "high")

    def test_entailment_but_not_official_stays_draft(self):
        # 判官支持但非官方源 → 停 draft、不展示（宁缺不编）
        st, kind, conf = decide_cycle_status("entailment", 0.9, False)
        self.assertEqual(st, "draft")
        self.assertEqual(kind, "public_aggregate")

    def test_official_but_low_confidence_stays_draft(self):
        st, kind, conf = decide_cycle_status("entailment", 0.5, True)
        self.assertEqual(st, "draft")

    def test_no_entailment_stays_draft(self):
        for verdict in ("neutral", "contradiction"):
            st, kind, conf = decide_cycle_status(verdict, 0.95, True)
            self.assertEqual(st, "draft")
            self.assertEqual(kind, "llm_draft")


if __name__ == "__main__":
    unittest.main()
