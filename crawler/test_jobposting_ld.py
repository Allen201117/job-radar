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


class ResolveOfficialTimesTest(unittest.TestCase):
    """resolve_official_times：JSON-LD > adapter 直填 > 正文正则（02 spec §3.2）。
    红线：posted_at 不取正文正则（§4 官方/结构化 only）。"""

    def _ld(self, posted="2026-06-10", deadline="2026-07-31"):
        return ('<script type="application/ld+json">'
                f'{{"@type":"JobPosting","datePosted":"{posted}","validThrough":"{deadline}"}}</script>')

    def test_jsonld_wins_over_adapter(self):
        out = normalizer.resolve_official_times(
            detail_html=self._ld(), adapter_posted="2026-01-01", adapter_deadline="2026-02-02")
        self.assertEqual(out["posted_at"], "2026-06-10")
        self.assertEqual(out["deadline"], "2026-07-31")

    def test_falls_back_to_adapter_when_no_jsonld(self):
        out = normalizer.resolve_official_times(
            detail_html="<html>no ld</html>", adapter_posted="2026/03/04", adapter_deadline="2026/05/06")
        self.assertEqual(out["posted_at"], "2026-03-04")  # coerce_iso_date 归一
        self.assertEqual(out["deadline"], "2026-05-06")

    def test_posted_at_never_from_body_regex(self):
        # 正文里有「发布于 …」，但 posted_at 仍须为 None（官方 only，不污染 NEWLY_DISCOVERED）。
        out = normalizer.resolve_official_times(
            detail_html=None, adapter_posted=None, adapter_deadline=None,
            body_text="发布于 2026-04-01。投递截止：2026-08-15")
        self.assertIsNone(out["posted_at"])
        self.assertEqual(out["deadline"], "2026-08-15")  # deadline 允许正文正则兜底

    def test_all_none(self):
        out = normalizer.resolve_official_times()
        self.assertEqual(out, {"posted_at": None, "deadline": None})


if __name__ == "__main__":
    unittest.main()
