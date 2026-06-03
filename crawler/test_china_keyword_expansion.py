"""中英双语关键词扩展/匹配的纯函数单测（移植自 lib/china-keyword-expansion.test.js 的关注点）。"""
import unittest

import china_keyword_expansion as cke


class NormalizeTest(unittest.TestCase):
    def test_lowercase_and_collapse_whitespace(self):
        self.assertEqual(cke.normalize_for_match("  Machine   Learning  "), "machine learning")
        self.assertEqual(cke.normalize_for_match(None), "")


class ContainsTermBoundaryTest(unittest.TestCase):
    def test_short_latin_uses_word_boundary(self):
        self.assertTrue(cke.contains_term("ai engineer", "ai"))
        self.assertTrue(cke.contains_term("senior ml researcher", "ml"))
        # 误匹配防护：maintain/google 不应被 ai/go 命中
        self.assertFalse(cke.contains_term("maintenance technician", "ai"))
        self.assertFalse(cke.contains_term("google maps lead", "go"))

    def test_long_or_cjk_uses_substring(self):
        self.assertTrue(cke.contains_term("machine learning engineer", "machine learning"))
        self.assertTrue(cke.contains_term("后端工程师", "后端"))
        self.assertFalse(cke.contains_term("财务分析", "算法"))


class ExpandTest(unittest.TestCase):
    def test_chinese_expands_to_english_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("算法"))
        for t in ("算法", "machine learning", "ml", "algorithm"):
            self.assertIn(t, terms, t)

    def test_english_expands_to_chinese_synonyms(self):
        terms = set(cke.expand_china_keyword_terms("backend"))
        for t in ("backend", "后端", "服务端"):
            self.assertIn(t, terms, t)

    def test_empty_query_returns_empty(self):
        self.assertEqual(cke.expand_china_keyword_terms(""), [])
        self.assertEqual(cke.expand_china_keyword_terms("   "), [])

    def test_unmatched_term_kept_verbatim(self):
        # 不在任何同义词组里的词应原样保留，仍可做子串匹配
        self.assertIn("blockchain", cke.expand_china_keyword_terms("blockchain"))


class QueryMatchesTest(unittest.TestCase):
    def test_chinese_query_matches_english_job(self):  # 核心 #4 场景
        self.assertTrue(cke.query_matches("Machine Learning Engineer", "算法"))
        self.assertTrue(cke.query_matches("AI Researcher", "算法"))
        self.assertTrue(cke.query_matches("Product Manager", "产品"))

    def test_english_query_matches_chinese_job(self):
        self.assertTrue(cke.query_matches("后端工程师 字节跳动", "backend"))

    def test_no_false_positive_via_short_abbrev(self):
        # 「算法」扩展含 "ai"，但 maintain/maintenance 不应被命中
        self.assertFalse(cke.query_matches("Maintenance Technician — maintain systems", "算法"))

    def test_empty_query_matches_all(self):
        self.assertTrue(cke.query_matches("anything", ""))

    def test_unrelated_query_no_match(self):
        self.assertFalse(cke.query_matches("Finance Analyst report", "前端"))


class ParityWithFrontendTest(unittest.TestCase):
    def test_group_count_matches_frontend(self):
        # 与 lib/china-keyword-expansion.js 的 21 组保持一致
        self.assertEqual(len(cke.CHINA_KEYWORD_GROUPS), 21)


if __name__ == "__main__":
    unittest.main()
