"""discover_domestic moka 校招板块探测单测（mock httpx client，不打真网络）。

红线：① 校招候选是独立于社招的第二条命中（各自 title-verify，互不覆盖）；
② 校招 URL 必须命中 CAMPUS_URL_RE（lib/campus-sources.ts 同款正则）才算「校招源」；
③ 租户没开校招板块（404/不存在/无 orgId）时不产出候选，不是错误。
"""
import re
import unittest
from unittest import mock

import discover_domestic as dd

# 与 lib/campus-sources.ts 的 CAMPUS_URL_RE 等价（校招源判定口径必须两端一致）。
CAMPUS_URL_RE = re.compile(r"campus|xiaozhao|校招|校园|campus_apply|/campus", re.I)


class _FakeResponse:
    def __init__(self, url, text):
        self.url = url
        self.text = text
        self.status_code = 200


class _FakeClient:
    """按 URL 前缀匹配返回预置响应；未匹配的 URL 视为测试疏漏，直接报错方便定位。"""

    def __init__(self, routes):
        self._routes = routes  # {url_prefix: _FakeResponse}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        for prefix, resp in self._routes.items():
            if url.startswith(prefix):
                return resp
        raise AssertionError(f"unexpected GET in test: {url}")


def _patched_client(routes):
    return mock.patch.object(dd, "_client", return_value=_FakeClient(routes))


class MokaCampusProbeTest(unittest.TestCase):
    """moka_probe 命中社招后顺带探校招板块，产出独立 campus 候选。"""

    def test_social_and_campus_both_found(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/jimi/142344",
                "<title>极米科技招聘 - 极米</title>"),
            "https://app.mokahr.com/campus-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/jimi/150242",
                "<title>极米科技校园招聘 - 极米</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("jimi", "极米")
        self.assertIsNotNone(r)
        self.assertTrue(r["verified"])
        self.assertIn("campus", r)
        self.assertEqual(r["campus"]["org_id"], "150242")
        self.assertEqual(r["campus"]["url"],
                         "https://app.mokahr.com/campus-recruitment/jimi/150242")
        # 校招 org 与社招 org 不同（极米 live 实测 142344 vs 150242）
        self.assertNotEqual(r["org_id"], r["campus"]["org_id"])

    def test_campus_absent_when_tenant_has_no_campus_board(self):
        """很多租户没开校招板块——不是错误，只是没有 campus 候选。"""
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo",
                "<title>您访问的页面不存在</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("foo", "foo公司")
        self.assertIsNotNone(r)
        self.assertNotIn("campus", r)

    def test_campus_title_mismatch_rejected(self):
        """校招页面 title 命中别的公司（疑似张冠李戴/租户复用）→ 独立拒绝，不因社招验证过就照单全收。"""
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo/11111",
                "<title>别家公司校园招聘</title>"),
        }
        with _patched_client(routes):
            r = dd.moka_probe("foo", "foo公司")
        self.assertIsNotNone(r)
        self.assertNotIn("campus", r)


class ProbeCompanyCampusSplitTest(unittest.TestCase):
    """_probe_company：社招/校招各自产出独立命中，campus URL 命中 CAMPUS_URL_RE。"""

    def test_produces_two_separate_hits(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/jimi/142344",
                "<title>极米科技招聘 - 极米</title>"),
            "https://app.mokahr.com/campus-recruitment/jimi": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/jimi/150242",
                "<title>极米科技校园招聘 - 极米</title>"),
        }
        target = {"company": "极米", "cn": "极米", "slugs": ["jimi"], "industry": "消费电子"}
        with _patched_client(routes):
            hits = dd._probe_company(target, {"moka"})
        self.assertEqual(len(hits), 2)
        social = next(h for h in hits if h.get("kind") != "campus")
        campus = next(h for h in hits if h.get("kind") == "campus")
        self.assertEqual(social["platform"], "moka")
        self.assertEqual(campus["platform"], "moka")
        self.assertTrue(campus["verified"])
        self.assertRegex(campus["url"], CAMPUS_URL_RE)
        self.assertNotRegex(social["url"], CAMPUS_URL_RE)  # 社招 URL 不应误判成校招

    def test_no_campus_board_yields_single_hit(self):
        routes = {
            "https://app.mokahr.com/social-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/social-recruitment/foo/98765",
                "<title>foo公司招聘 - foo</title>"),
            "https://app.mokahr.com/campus-recruitment/foo": _FakeResponse(
                "https://app.mokahr.com/campus-recruitment/foo",
                "<title>您访问的页面不存在</title>"),
        }
        target = {"company": "foo公司", "cn": "foo公司", "slugs": ["foo"], "industry": "x"}
        with _patched_client(routes):
            hits = dd._probe_company(target, {"moka"})
        self.assertEqual(len(hits), 1)
        self.assertNotEqual(hits[0].get("kind"), "campus")


class ToMokaCandidatesCampusTest(unittest.TestCase):
    """to_moka_candidates：社招与校招命中各自转成独立候选，均通过质量门（verified）才入选。"""

    def test_both_kinds_become_candidates(self):
        hits = [
            {"platform": "moka", "company": "极米", "industry": "消费电子", "verified": True,
             "url": "https://app.mokahr.com/social-recruitment/jimi/142344"},
            {"platform": "moka", "kind": "campus", "company": "极米", "industry": "消费电子",
             "verified": True, "url": "https://app.mokahr.com/campus-recruitment/jimi/150242"},
        ]
        cands = dd.to_moka_candidates(hits)
        self.assertEqual(len(cands), 2)
        urls = {c["url"] for c in cands}
        self.assertIn("https://app.mokahr.com/campus-recruitment/jimi/150242", urls)
        campus_cand = next(c for c in cands if c["kind"] == "campus")
        self.assertRegex(campus_cand["url"], CAMPUS_URL_RE)
        self.assertEqual(campus_cand["adapter"], "moka")

    def test_unverified_dropped_even_with_campus_kind(self):
        hits = [{"platform": "moka", "kind": "campus", "company": "X", "verified": False,
                "url": "https://app.mokahr.com/campus-recruitment/x/1"}]
        self.assertEqual(dd.to_moka_candidates(hits), [])


if __name__ == "__main__":
    unittest.main()
