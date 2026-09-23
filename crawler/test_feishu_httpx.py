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

    def test_index_url_is_marked_main_portal(self):
        """/index/position 与根路径 = 主门户：website_path 留空、标 _main_portal，由 _httpx_fetch_main 带头去取
        （2026-09-23 更正：旧版这里钉的是「index 是子集、主门户不带头」，见 MainPortalTest）。"""
        for url in ("https://nio.jobs.feishu.cn/index/position",
                    "https://nio.jobs.feishu.cn/",
                    "https://nio.jobs.feishu.cn"):
            a = self._a(url)
            self.assertEqual(a.website_path, "", url)
            self.assertTrue(a._main_portal, url)
            self.assertEqual(a.detail_template,
                             "https://nio.jobs.feishu.cn/index/position/{id}/detail", url)
        self.assertFalse(self._a("https://nio.jobs.feishu.cn/campus/position")._main_portal)

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

    def test_headers_sent_per_portal(self):
        """子门户只带自己的头；主门户带「自报门户」和「index」两个头各取一次，绝不再不带头。"""
        for url, declared, expect in (("https://nio.jobs.feishu.cn/campus/position", "index", ["campus"]),
                                      ("https://nio.jobs.feishu.cn/index/position", "career", ["career", "index"]),
                                      ("https://nio.jobs.feishu.cn/index/position", "index", ["index"])):
            sent = []

            class _CapClient(_FakeClient):
                def __init__(self, pages, **kw):
                    super().__init__(pages)
                    sent.append((kw.get("headers") or {}).get("website-path"))
                    assert "portal-channel" in (kw.get("headers") or {})

            a = self._a(url)
            a._PAGE_SIZE = 2
            with mock.patch.object(feishu.httpx, "Client", lambda **kw: _CapClient([_page([1], 1)], **kw)), \
                    mock.patch.object(a, "_discover_detail_prefix", return_value=declared):
                a._httpx_fetch("nio.jobs.feishu.cn")
            self.assertEqual(sent, expect, url)


class MainPortalTest(unittest.TestCase):
    """主门户抓「公开门户」而不是「不带头的全集」（2026-09-23 更正 2026-09-04 的结论）。

    碑文（133 个飞书系源逐岗全量核，详情接口带 `website-path:<链接所在门户>` 读 channel_online_status）：
      · 不带头多出来的岗在公开门户上显示「该职位已下线」（浏览器实开核对：去哪儿 / 网眼科技）；
      · channel_online_status 按门户算——同一岗不带头读 1、带 index 头读 0；
      · 带门户头取回的列表，逐岗在该门户上是 1；
      · 有租户开两个公开门户（莉莉丝 career 119 / index 57），只取一个会漏在线岗 → 取并集、各用各的前缀；
      · 「不带头 ⊇ 门户」也不成立（超级猩猩不带头 6 / 门户 17）。
    """

    def _a(self):
        a = feishu.NioAdapter()
        a._bind_website_path("https://nio.jobs.feishu.cn/index/position")
        a._PAGE_SIZE = 50
        return a

    @staticmethod
    def _client_by_portal(pages_by_portal):
        def factory(**kw):
            portal = (kw.get("headers") or {}).get("website-path")
            return _FakeClient(list(pages_by_portal.get(portal, [_page([], 0)])))
        return factory

    def test_union_of_declared_and_index_with_per_row_prefix(self):
        a = self._a()
        pages = {"career": [_page([1, 2, 3], 3)], "index": [_page([3, 4], 2)]}
        with mock.patch.object(feishu.httpx, "Client", self._client_by_portal(pages)), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="career"):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertTrue(reached)
        self.assertEqual(total, 4)                                   # 两个门户都翻全 → 抓全
        self.assertEqual({r["id"]: r["_portal"] for r in rows},
                         {"1": "career", "2": "career", "3": "career", "4": "index"})
        jobs = {j.jd_url for j in (a._map(r) for r in rows)}
        self.assertIn("https://nio.jobs.feishu.cn/career/position/1/detail", jobs)
        self.assertIn("https://nio.jobs.feishu.cn/index/position/4/detail", jobs)   # 只在 index 的用 index
        self.assertEqual(a.detail_template, "https://nio.jobs.feishu.cn/career/position/{id}/detail")

    def test_declared_index_fetches_once(self):
        a = self._a()
        calls = []

        def factory(**kw):
            calls.append((kw.get("headers") or {}).get("website-path"))
            return _FakeClient([_page([1], 1)])

        with mock.patch.object(feishu.httpx, "Client", factory), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="index"):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertEqual(calls, ["index"])
        self.assertEqual((len(rows), total), (1, 1))

    def test_unknown_declared_portal_is_never_complete(self):
        """首页拿不到自报门户 → 只取 index，但**不许**标抓全：否则 list-absence 会按它判撤岗。"""
        a = self._a()
        with mock.patch.object(feishu.httpx, "Client", self._client_by_portal({"index": [_page([1], 1)]})), \
                mock.patch.object(a, "_discover_detail_prefix", return_value=""):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
            a._prefetched = (rows, total, reached)
            a.fetch("https://nio.jobs.feishu.cn/index/position")
        self.assertEqual([r["id"] for r in rows], ["1"])
        self.assertIsNone(total)
        self.assertFalse(a.fetch_complete)

    def test_one_portal_not_fully_paged_is_not_complete(self):
        a = self._a()
        a._MAX_JOBS = 2
        pages = {"career": [_page([1, 2], 5)], "index": [_page([9], 1)]}
        with mock.patch.object(feishu.httpx, "Client", self._client_by_portal(pages)), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="career"):
            rows, total, reached = a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertIsNone(total)

    def test_declared_prefix_does_not_leak_to_next_source(self):
        """probe.probe_one 共用单例：上一家自报 exp，下一家首页没自报 → 模板必须回到 index。"""
        a = self._a()
        with mock.patch.object(feishu.httpx, "Client", self._client_by_portal({})), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="exp"):
            a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertIn("/exp/position/", a.detail_template)
        with mock.patch.object(feishu.httpx, "Client", self._client_by_portal({})), \
                mock.patch.object(a, "_discover_detail_prefix", return_value=""):
            a._httpx_fetch("nio.jobs.feishu.cn")
        self.assertIn("/index/position/", a.detail_template)

    def test_missing_index_portal_counts_as_empty_not_unreached(self):
        """小马智行 / 商汤：没有 index 门户，接口回 -9000003 site not exist → 当空门户，照样能标抓全。"""
        a = self._a()

        def factory(**kw):
            portal = (kw.get("headers") or {}).get("website-path")
            if portal == "index":
                return _FakeClient([{"code": -9000003, "message": "site not exist", "data": None}])
            return _FakeClient([_page([1, 2], 2)])

        with mock.patch.object(feishu.httpx, "Client", factory), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="ponyai"):
            rows, total, reached = a._httpx_fetch("ponyai.jobs.feishu.cn")
        self.assertEqual((len(rows), total, reached), (2, 2, True))

    def test_missing_declared_portal_is_not_waved_through(self):
        """自报门户本身回 site not exist 是异常，不许当空门户（否则会把全源判成 0 岗、抓全）。"""
        a = self._a()
        with mock.patch.object(feishu.httpx, "Client",
                               lambda **kw: _FakeClient([{"code": -9000003, "data": None}])), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="exp"):
            rows, total, reached = a._httpx_fetch("x.jobs.feishu.cn")
        self.assertIsNone(total)

    def test_declared_portal_with_zero_jobs_is_a_real_zero(self):
        """海底捞：自报门户（校园招聘 072846）0 岗、没有 index 门户、不带头却回 151 个
        ——那 151 个在公开页全是「已下线」（公开首页「开启新的工作（0）」）。真 0 岗就是 0 岗。"""
        a = self._a()

        def factory(**kw):
            portal = (kw.get("headers") or {}).get("website-path")
            if portal == "index":
                return _FakeClient([{"code": -9000003, "data": None}])
            return _FakeClient([_page([], 0)])

        with mock.patch.object(feishu.httpx, "Client", factory), \
                mock.patch.object(a, "_discover_detail_prefix", return_value="072846"):
            rows, total, reached = a._httpx_fetch("haidilao.jobs.feishu.cn")
        self.assertEqual((rows, total, reached), ([], 0, True))

    def test_detail_check_uses_the_rows_own_portal(self):
        a = self._a()
        seen = []
        ok = type("Response", (), {"status_code": 200, "text": "x"})()
        with mock.patch.object(feishu.httpx, "get", side_effect=lambda u, **k: seen.append(u) or ok):
            self.assertFalse(a._detail_portal_closed("nio.jobs.feishu.cn", {"id": "7", "_portal": "career"}))
        self.assertEqual(seen, ["https://nio.jobs.feishu.cn/career/position/7/detail"])


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
