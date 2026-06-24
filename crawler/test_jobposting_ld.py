"""02 spec §3.2 / §6.1：JSON-LD JobPosting 抽取——datePosted→posted_at、validThrough→deadline，归一 ISO date。
容忍 @graph / 对象数组 / 单对象 / @type 数组；无 JobPosting 或解析失败返回 None。"""
import unittest

import normalizer


def wrap(json_text):
    return f'<html><head><script type="application/ld+json">{json_text}</script></head></html>'


class JobPostingLdTest(unittest.TestCase):
    def test_single_jobposting(self):
        html = wrap('{"@type":"JobPosting","datePosted":"2026-06-01","validThrough":"2026-07-01T23:59:59Z"}')
        out = normalizer.extract_jobposting_ld(html)
        self.assertEqual(out["posted_at"], "2026-06-01")
        self.assertEqual(out["deadline"], "2026-07-01")

    def test_graph_array(self):
        html = wrap('{"@context":"https://schema.org","@graph":['
                    '{"@type":"Organization","name":"X"},'
                    '{"@type":"JobPosting","datePosted":"2026/05/20"}]}')
        out = normalizer.extract_jobposting_ld(html)
        self.assertEqual(out["posted_at"], "2026-05-20")
        self.assertIsNone(out["deadline"])

    def test_type_as_array(self):
        html = wrap('{"@type":["JobPosting","Thing"],"datePosted":"2026-06-10"}')
        self.assertEqual(normalizer.extract_jobposting_ld(html)["posted_at"], "2026-06-10")

    def test_array_of_nodes(self):
        html = wrap('[{"@type":"WebPage"},{"@type":"JobPosting","validThrough":"2026-08-15"}]')
        out = normalizer.extract_jobposting_ld(html)
        self.assertEqual(out["deadline"], "2026-08-15")

    def test_no_jobposting_returns_none(self):
        html = wrap('{"@type":"Organization","name":"X"}')
        out = normalizer.extract_jobposting_ld(html)
        self.assertEqual(out, {"posted_at": None, "deadline": None})

    def test_malformed_json_safe(self):
        html = wrap('{not valid json,,,}')
        self.assertEqual(normalizer.extract_jobposting_ld(html), {"posted_at": None, "deadline": None})

    def test_no_ld_block(self):
        self.assertEqual(
            normalizer.extract_jobposting_ld("<html><body>no ld here</body></html>"),
            {"posted_at": None, "deadline": None},
        )

    def test_empty_input(self):
        self.assertEqual(normalizer.extract_jobposting_ld(None), {"posted_at": None, "deadline": None})
        self.assertEqual(normalizer.extract_jobposting_ld(""), {"posted_at": None, "deadline": None})


if __name__ == "__main__":
    unittest.main()
