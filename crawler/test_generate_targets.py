"""generate_targets 纯函数单测（不打真网络、不连库、不调 LLM）。

红线：LLM 产物只是探测输入，本层负责清洗/去重/防脏 slug；真正入库门在下游探活验证。
"""
import datetime
import os
import unittest

import generate_targets as gt


class ParseGeneratedTest(unittest.TestCase):
    def test_extracts_valid_and_marks_llm_priority(self):
        data = {"companies": [
            {"company": "小红书", "cn": "小红书", "slugs": ["xiaohongshu", "xhs"], "industry": "互联网"},
        ]}
        out = gt.parse_generated(data, set())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["company"], "小红书")
        self.assertTrue(out[0]["_priority"] and out[0]["_llm"])   # 优先探 + 标记 LLM 来源
        self.assertEqual(out[0]["slugs"], ["xiaohongshu", "xhs"])

    def test_dedups_against_existing_companies(self):
        data = {"companies": [
            {"company": "美团", "slugs": ["meituan"], "industry": "x"},
            {"company": "得物", "slugs": ["dewu"], "industry": "x"},
        ]}
        out = gt.parse_generated(data, {"美团"})
        self.assertEqual([c["company"] for c in out], ["得物"])   # 库里已有 → 不重复

    def test_dedups_within_batch(self):
        data = {"companies": [
            {"company": "A", "slugs": ["a"]},
            {"company": "A", "slugs": ["a2"]},
        ]}
        out = gt.parse_generated(data, set())
        self.assertEqual(len(out), 1)

    def test_drops_company_without_slugs(self):
        data = {"companies": [{"company": "无slug", "slugs": []}, {"company": "B", "slugs": ["b"]}]}
        out = gt.parse_generated(data, set())
        self.assertEqual([c["company"] for c in out], ["B"])

    def test_cleans_bad_slugs_keeps_good(self):
        data = {"companies": [{"company": "C", "slugs": ["good", "has space", "", "ok2"]}]}
        out = gt.parse_generated(data, set())
        self.assertEqual(out[0]["slugs"], ["good", "ok2"])       # 带空格/空的 slug 剔除

    def test_caps_slugs_at_four(self):
        data = {"companies": [{"company": "D", "slugs": ["a", "b", "c", "d", "e", "f"]}]}
        out = gt.parse_generated(data, set())
        self.assertEqual(len(out[0]["slugs"]), 4)

    def test_tolerates_missing_or_bad_shape(self):
        self.assertEqual(gt.parse_generated({}, set()), [])
        self.assertEqual(gt.parse_generated({"companies": ["not-a-dict"]}, set()), [])
        self.assertEqual(gt.parse_generated(None, set()), [])


class ThemeAndGuardTest(unittest.TestCase):
    def test_theme_rotates_deterministically(self):
        d1 = datetime.date(2026, 7, 2)
        self.assertEqual(gt.theme_for(d1), gt.theme_for(d1))     # 同日同主题（可复现）
        # 覆盖全部主题：连续 len(_THEMES) 天应取到不同主题
        seen = {gt.theme_for(d1 + datetime.timedelta(days=i))[0] for i in range(len(gt._THEMES))}
        self.assertEqual(len(seen), len(gt._THEMES))

    def test_no_api_key_returns_empty(self):
        old = os.environ.pop("SILICONFLOW_API_KEY", None)
        try:
            self.assertEqual(gt.llm_generate({"美团"}, n=10), [])  # 无 key → 安全回退，不打网络
        finally:
            if old is not None:
                os.environ["SILICONFLOW_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
