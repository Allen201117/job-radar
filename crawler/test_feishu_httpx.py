"""feishu httpx-first 抓取单测（mock httpx，不打真网络）。

覆盖：① _httpx_fetch 翻页/去重/抓全判定/真0岗 reached ② fetch() 决策——reached 用 httpx 不开浏览器、
reached=False 回退浏览器、complete 计算（翻到 count=True / 撞 _MAX_JOBS 上限=False）。
红线：httpx 没打通(reached=False)才回退浏览器；抓不全(撞上限)绝不让 list-absence 误判。
"""
import json
import unittest
from unittest import mock

from adapters import feishu


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    """按预设页序返回 posts API 响应；构造接受任意 kwargs（与真 httpx.Client 同签名）。"""
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None):
        i = self.calls
        self.calls += 1
        if i < len(self.pages):
            return _Resp(self.pages[i])
        return _Resp({"data": {"job_post_list": [], "count": 0}})


def _page(ids, count):
    return {"data": {"job_post_list": [{"id": str(x), "title": f"T{x}"} for x in ids], "count": count}}


def _patch_client(pages):
    return mock.patch.object(feishu.httpx, "Client", lambda **kw: _FakeClient(pages))


class WebsitePathTest(unittest.TestCase):
    """子门户（website-path 请求头）—— 校招/实习岗藏在这里。

    2026-09-04 实测：小米不带该头 1894 / campus 764 / internship 554 / newretailing 121，
    四个池子互不相同；蔚来 campus 920 个岗全是「校招-…」。
    此前判「飞书私有部署没有校招板块」是错的，错在试的是 storefront_id 而不是这个头。
    """

    def _a(self, url):
        a = feishu.NioAdapter()
        a._bind_website_path(url)
        return a

    def test_campus_path_is_derived_from_source_url(self):
        a = self._a("https://nio.jobs.feishu.cn/campus/position")
        self.assertEqual(a.website_path, "campus")
        self.assertEqual(a.detail_template,
                         "https://nio.jobs.feishu.cn/campus/position/{id}/detail")
        self.assertEqual(a.list_urls[0], "https://nio.jobs.feishu.cn/campus/position")

    def test_index_must_not_become_a_website_path(self):
        """⚠️ 主门户带 `website-path: index` 拿到的是**子集**：蔚来 2055 → 1801，少 254 个岗。
        库里 70 个存量飞书源全是 /index/position，派生 index 就是全体缩水。"""
        for url in ("https://nio.jobs.feishu.cn/index/position",
                    "https://nio.jobs.feishu.cn/",
                    "https://nio.jobs.feishu.cn"):
            a = self._a(url)
            self.assertEqual(a.website_path, "", url)
            self.assertEqual(a.detail_template,
                             "https://nio.jobs.feishu.cn/index/position/{id}/detail", url)

    def test_other_custom_portals_are_derived(self):
        for path, expected in (("internship", "internship"), ("newretailing", "newretailing"),
                               ("ponyai", "ponyai")):
            a = self._a(f"https://nio.jobs.feishu.cn/{path}/position")
            self.assertEqual(a.website_path, expected)

    def test_generic_adapter_keeps_real_host_in_detail_template(self):
        """⚠️ 通用类的 self.host 是空串，真实 host 在 official_hosts 里（由 _bind_host 放进去）。

        早先 _apply_website_path 直接用 self.host，把 _bind_host 刚算好的 detail_template
        覆写成 `https:///index/position/{id}/detail` → jd_url 全废 → **68 个通用飞书源
        解析出 0 岗却仍标 fetch_complete=True**（2026-09-04 实测拓竹 reported=165/parsed=0）。
        这正是「0 岗 + 自称抓全」的红线组合。
        """
        for url, expect in (
            ("https://bambulab.jobs.feishu.cn/campus/position",
             "https://bambulab.jobs.feishu.cn/campus/position/{id}/detail"),
            ("https://li.jobs.feishu.cn/index/position",
             "https://li.jobs.feishu.cn/index/position/{id}/detail"),
            ("https://ponyai.jobs.feishu.cn/ponyai/position",
             "https://ponyai.jobs.feishu.cn/ponyai/position/{id}/detail"),
        ):
            a = feishu.FeishuGenericAdapter()
            a._bind_host(url)
            a._bind_website_path(url)
            self.assertEqual(a.detail_template, expect, url)
            self.assertNotIn("https:///", a.detail_template, url)

    def test_apply_website_path_is_a_noop_before_host_is_bound(self):
        """通用类构造完还没绑 host —— 此时不许把模板写成空 host。"""
        a = feishu.FeishuGenericAdapter()
        a._apply_website_path("campus")
        self.assertEqual(a.detail_template, "")

    def test_header_sent_only_for_sub_portals(self):
        captured = {}

        class _CapClient(_FakeClient):
            def __init__(self, pages, **kw):
                super().__init__(pages)
                captured["headers"] = kw.get("headers") or {}

        for url, expect_header in (("https://nio.jobs.feishu.cn/campus/position", "campus"),
                                   ("https://nio.jobs.feishu.cn/index/position", None)):
            captured.clear()
            a = self._a(url)
            a._PAGE_SIZE = 2
            with mock.patch.object(feishu.httpx, "Client",
                                   lambda **kw: _CapClient([_page([1], 1)], **kw)):
                a._httpx_fetch("nio.jobs.feishu.cn")
            self.assertEqual(captured["headers"].get("website-path"), expect_header, url)
            self.assertIn("portal-channel", captured["headers"])


class HttpxFetchTest(unittest.TestCase):
    def _adapter(self, page_size=2, max_jobs=10):
        a = feishu.NioAdapter()
        a._PAGE_SIZE = page_size
        a._MAX_JOBS = max_jobs
        return a

    def test_single_page_complete(self):
        a = self._adapter()
        with _patch_client([_page([1, 2], 2)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(total, 2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(reached)

    def test_paginates_and_dedups_to_count(self):
        a = self._adapter(page_size=2)
        # page0=[1,2], page1=[2,3] —— 2 跨页重复应去重，收齐 count=3
        with _patch_client([_page([1, 2], 3), _page([2, 3], 3)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(total, 3)
        self.assertEqual(sorted(r["id"] for r in rows), ["1", "2", "3"])
        self.assertTrue(reached)

    def test_short_page_does_not_end_pagination_when_total_known(self):
        """限流/抖动回一个短页，不许当末页收工（同 beisen 那条：判据要看有没有新岗，不看页长）。"""
        a = self._adapter(page_size=2, max_jobs=100)
        with _patch_client([_page([1, 2], 5), _page([3], 5), _page([4, 5], 5)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(len(rows), 5)
        self.assertEqual(total, 5)

    def test_page_with_no_new_ids_stops_pagination(self):
        """接口重复回同一批 → 停，别一路翻到上限白烧配额。"""
        a = self._adapter(page_size=2, max_jobs=100)
        with _patch_client([_page([1, 2], 99), _page([1, 2], 99), _page([3], 99)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(len(rows), 2)

    def test_caps_at_max_jobs_not_complete(self):
        a = self._adapter(page_size=2, max_jobs=2)
        with _patch_client([_page([1, 2], 9), _page([3, 4], 9)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(len(rows), 2)        # 撞上限即停
        self.assertTrue(reached)
        self.assertLess(len(rows), total)     # < total → fetch() 会判 not complete

    def test_real_zero_jobs_is_reached(self):
        a = self._adapter()
        with _patch_client([_page([], 0)]):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(rows, [])
        self.assertEqual(total, 0)
        self.assertTrue(reached)              # 真 0 岗也算打通，不回退浏览器


class FetchDecisionTest(unittest.TestCase):
    def test_closed_detail_portal_skips_whole_tenant(self):
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        closed = type("Response", (), {"status_code": 404, "text": "Not Found"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", return_value=closed) as get:
            reason = a.should_skip("https://nio.jobs.feishu.cn/index/position")
        self.assertIn("detail portal closed", reason)
        # 判死前最多两个请求：① 抽一岗试详情 ② 取首页问租户真实门户前缀（_repair_detail_template）。
        # 这条断言守的是「别按岗位数扇出去探」，不是守具体次数——但也别让它悄悄涨上去。
        self.assertEqual(get.call_count, 2)

    def test_wrong_prefix_is_repaired_instead_of_skipping_whole_tenant(self):
        """`index` 详情 404 但租户自报了别的门户前缀 → 换前缀重试，通了就别跳整源。

        2026-09-04 live 实测的两家：商汤 path=exp（整源被跳、84 岗进不来）、
        海底捞 path=072846（列表 119 岗正常，但 jd_url 全 404）。
        """
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        root = type("Response", (), {
            "status_code": 200,
            "text": '{"website_info":{"id":"7","name":{"i18n":"社招官网"},"language":"zh-CN","path":"exp"}}',
        })()
        closed = type("Response", (), {"status_code": 404, "text": "Not Found"})()
        live = type("Response", (), {"status_code": 200, "text": "job detail"})()

        def fake_get(url, **kw):
            if url.endswith("/"):
                return root                      # 租户首页：自报 path=exp
            return live if "/exp/position/" in url else closed

        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", side_effect=fake_get):
            self.assertIsNone(a.should_skip("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(a.detail_template, "https://nio.jobs.feishu.cn/exp/position/{id}/detail")
        # ⚠️ 只改详情模板，不动 website_path：海底捞的 072846 门户列表返 0 岗，
        # 顺手把它当子门户塞进请求头会把列表从 119 打成 0。
        self.assertEqual(a.website_path, "")

    def test_repaired_prefix_survives_the_rebind_inside_fetch(self):
        """修好的前缀必须扛住 `fetch()` 里那次 `_bind_website_path` 重算。

        2026-09-04 端到端实测抓到的回归：没有 override 时 should_skip 已经不跳了，
        但 fetch() 重算把 detail_template 覆写回 `index`，于是 80 个岗照样带着
        404 的 jd_url 入库 —— 比整源跳过更坏（死链比没有更伤信任）。
        """
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        root = type("Response", (), {
            "status_code": 200, "text": '{"website_info":{"name":{"i18n":"x"},"path":"exp"}}',
        })()
        closed = type("Response", (), {"status_code": 404, "text": "Not Found"})()
        live = type("Response", (), {"status_code": 200, "text": "job detail"})()

        def fake_get(url, **kw):
            if url.endswith("/"):
                return root
            return live if "/exp/position/" in url else closed

        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", side_effect=fake_get):
            self.assertIsNone(a.should_skip("https://nio.jobs.feishu.cn/index/position"))
            a.fetch("https://nio.jobs.feishu.cn/index/position")   # 这里会重算一次
        self.assertEqual(a.detail_template, "https://nio.jobs.feishu.cn/exp/position/{id}/detail")

    def test_untouched_tenants_keep_the_index_prefix(self):
        """对照组：`index` 详情本来就通的租户，一个字节都不该被改（全库 85 家里 83 家是这种）。"""
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        live = type("Response", (), {"status_code": 200, "text": "job detail"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", return_value=live) as get:
            self.assertIsNone(a.should_skip("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(a.detail_template, "https://nio.jobs.feishu.cn/index/position/{id}/detail")
        self.assertEqual(get.call_count, 1, "详情通了就不该再去取首页")

    def test_still_skips_when_repaired_prefix_also_fails(self):
        """自报前缀也 404 → 这才是真的门户关了，照旧整源跳过。"""
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        root = type("Response", (), {
            "status_code": 200, "text": '{"website_info":{"name":{"i18n":"x"},"path":"exp"}}',
        })()
        closed = type("Response", (), {"status_code": 404, "text": "Not Found"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get",
                                  side_effect=lambda u, **k: root if u.endswith("/") else closed):
            reason = a.should_skip("https://nio.jobs.feishu.cn/index/position")
        self.assertIn("detail portal closed", reason)

    def test_no_declared_path_still_skips(self):
        """首页拿不到 website_info → 没有可试的前缀，不做无根据的猜测，照旧跳过。"""
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        blank = type("Response", (), {"status_code": 200, "text": "<html>no portal info</html>"})()
        closed = type("Response", (), {"status_code": 404, "text": "Not Found"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get",
                                  side_effect=lambda u, **k: blank if u.endswith("/") else closed):
            self.assertIn("detail portal closed",
                          a.should_skip("https://nio.jobs.feishu.cn/index/position"))

    def test_reachable_detail_portal_keeps_prefetched_jobs(self):
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        live = type("Response", (), {"status_code": 200, "text": "job detail"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", return_value=live) as get:
            self.assertIsNone(a.should_skip("https://nio.jobs.feishu.cn/index/position"))
            out = json.loads(a.fetch("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(out["_intercepted"][0]["data"]["job_post_list"], rows)
        self.assertEqual(get.call_count, 1)

    def test_200_html_with_not_found_text_does_not_skip_tenant(self):
        a = feishu.NioAdapter()
        rows = [{"id": "1", "title": "T"}]
        spa_shell = type("Response", (), {"status_code": 200, "text": "i18n: Not Found"})()
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 1, True)), \
                mock.patch.object(feishu.httpx, "get", return_value=spa_shell):
            self.assertIsNone(a.should_skip("https://nio.jobs.feishu.cn/index/position"))

    def test_reached_complete_sets_flag_and_envelope(self):
        a = feishu.NioAdapter()
        with mock.patch.object(a, "_httpx_fetch", return_value=([{"id": "1", "title": "T"}], 1, True)):
            out = json.loads(a.fetch("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(out["_intercepted"][0]["data"]["count"], 1)
        self.assertTrue(a.fetch_complete)

    def test_reached_but_capped_not_complete(self):
        a = feishu.NioAdapter()
        rows = [{"id": str(i), "title": "T"} for i in range(600)]
        with mock.patch.object(a, "_httpx_fetch", return_value=(rows, 2491, True)):
            a.fetch("https://nio.jobs.feishu.cn/index/position")
        self.assertFalse(a.fetch_complete)    # 抓不全 → absence 不会误判

    def test_reached_zero_returns_empty_no_browser(self):
        a = feishu.NioAdapter()
        called = {"browser": False}

        def _boom(_url):
            called["browser"] = True
            return "BROWSER"

        with mock.patch.object(a, "_httpx_fetch", return_value=([], 0, True)), \
                mock.patch.object(a, "_browser_fetch", _boom):
            out = json.loads(a.fetch("https://nio.jobs.feishu.cn/index/position"))
        self.assertEqual(out["_intercepted"][0]["data"]["job_post_list"], [])
        self.assertTrue(a.fetch_complete)
        self.assertFalse(called["browser"])   # httpx 打通即用，绝不多开浏览器

    def test_not_reached_falls_back_to_browser(self):
        a = feishu.NioAdapter()
        with mock.patch.object(a, "_httpx_fetch", return_value=([], None, False)), \
                mock.patch.object(a, "_browser_fetch", return_value="BROWSER"):
            self.assertEqual(a.fetch("https://nio.jobs.feishu.cn/index/position"), "BROWSER")
        self.assertFalse(a.fetch_complete)


if __name__ == "__main__":
    unittest.main()
