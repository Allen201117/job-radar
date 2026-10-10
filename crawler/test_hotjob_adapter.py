"""HotJob / wecruit 通用 adapter 单测 — 构造公开列表接口响应，不打真实网络。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
import adapters.hotjob as hotjob_mod
from adapters.hotjob import HotJobAdapter


TCL_LIST_RESPONSE = {
    "data": {
        "pageForm": {
            "pageData": [
                {
                    "postId": "69a2980b8e515379dcfe3dc6",
                    "postName": "BW/HANA顾问",
                    "workPlaceStr": "深圳市",
                    "postTypeName": "研发技术类",
                    "workContent": "负责 BW/HANA 系统建设。",
                    "serviceCondition": "本科及以上。",
                    "publishDate": "2026-06-05 14:06:32",
                },
                {
                    "postId": "missing-title",
                    "workPlaceStr": "深圳市",
                },
            ]
        }
    }
}


class TestHotJobAdapter(unittest.TestCase):
    def setUp(self):
        self.a = HotJobAdapter()
        self.a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html")

    def test_bind_source_builds_detail_template_and_list_urls(self):
        self.assertEqual(self.a._suite_key, "SU64893571bef57c16d356b99e")
        self.assertEqual(self.a.official_hosts, ("wecruit.hotjob.cn",))
        self.assertIn(
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html",
            self.a.list_urls,
        )
        self.assertEqual(
            self.a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=society",
        )

    def test_bind_source_maps_school_and_intern_detail_post_type(self):
        a = HotJobAdapter()
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/school.html")
        self.assertEqual(
            a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=campus",
        )
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/interns.html")
        self.assertEqual(
            a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=intern",
        )

    def test_bind_source_sets_recruit_type_per_channel(self):
        # recruitType 数值经各页 JS bundle 核实：society=2 / campus=1 / intern=12（直连接口的渠道选择子）。
        a = HotJobAdapter()
        a._bind_source("https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/social.html")
        self.assertEqual(a._recruit_type, 2)
        self.assertEqual(a._origin, "https://crrc.hotjob.cn")
        a._bind_source("https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/school.html")
        self.assertEqual(a._recruit_type, 1)
        a._bind_source("https://crrc.hotjob.cn/SU64d47c466202cc36e27a52d4/pb/interns.html")
        self.assertEqual(a._recruit_type, 12)

    def test_bind_source_defaults_to_society_when_page_missing(self):
        a = HotJobAdapter()
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e")
        self.assertEqual(a._recruit_type, 2)
        self.assertTrue(a.detail_template.endswith("postType=society"))

    def test_parse_list_position_builds_detail_jobs(self):
        jobs = self.a.parse(json.dumps({"_intercepted": [TCL_LIST_RESPONSE]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "BW/HANA顾问")
        self.assertEqual(jobs[0].location, "深圳市")
        self.assertEqual(jobs[0].job_type, "研发技术类")
        self.assertEqual(jobs[0].posted_at, "2026-06-05")
        self.assertEqual(
            jobs[0].jd_url,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId=69a2980b8e515379dcfe3dc6&postType=society",
        )
        self.assertIn("负责 BW/HANA", jobs[0].summary)
        self.assertIn("本科及以上", jobs[0].summary)

    def test_quality_gate_passes_hotjob_detail_url(self):
        jobs = self.a.parse(json.dumps({"_intercepted": [TCL_LIST_RESPONSE]}))
        jobs[0].company = "TCL"
        ok, reason = normalizer.validate_job_quality(
            jobs[0],
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html",
        )
        self.assertTrue(ok, reason)


class TestHotJobDeadline(unittest.TestCase):
    """endDate 只有 longTermRelease == 1 时才是截止日（2026-10-10 立）。

    依据是平台自己的前端：`0 === longTermRelease ? "长期发布" : format(endDate)`（「下线时间」那一栏）。
    当天全量 147 个源 20,626 个岗：longTermRelease=0 的 17,655 个里 endDate 是 3000-01-01 7,191 /
    已过去却仍在列 749（最早 2019 年）/ 550 天以外的占位 2,832 / 550 天以内的未来日期 6,883
    （其中 3,075 个是每晚 02:10 前后续成「+7 天」的滚动值）；longTermRelease=1 的 2,971 个没有一个是过去的日期。
    """

    def setUp(self):
        self.a = HotJobAdapter()
        self.a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html")

    def _deadline(self, end, flag):
        post = {"postId": "p1", "postName": "某岗", "endDate": end}
        if flag is not None:
            post["longTermRelease"] = flag
        return self.a._map(post).deadline

    def test_long_term_post_never_gets_a_deadline(self):
        for end in ("3000-01-01 23:59:59",   # 占位
                    "2026-10-17 02:11:46",   # 每晚续 7 天的滚动值：08-26 存的是 09-02，10-10 再问是 10-17
                    "2027-10-09 23:59:59",   # 发布日 + 12 个月；官网页面写的是「长期发布」
                    "2079-11-30 23:59:59",   # 远未来占位
                    "2023-06-26 23:59:59"):  # 三年前，详情页照样有「立即投递」
            self.assertIsNone(self._deadline(end, 0), end)

    def test_post_with_offline_time_keeps_its_date(self):
        # 官网页面原文：「2026-10-22 23:59:59下线」
        self.assertEqual(self._deadline("2026-10-22 23:59:59", 1), "2026-10-22")
        self.assertEqual(self._deadline("2026-12-15 12:59:00", "1"), "2026-12-15")

    def test_missing_or_unknown_flag_means_no_deadline(self):
        """判不出就不写：缺字段 / 取值不认识，一律当成没有截止日。"""
        self.assertIsNone(self._deadline("2026-10-22 23:59:59", None))
        self.assertIsNone(self._deadline("2026-10-22 23:59:59", 2))
        self.assertIsNone(self._deadline("2026-10-22 23:59:59", True))

    def test_unparseable_end_date_is_dropped(self):
        self.assertIsNone(self._deadline("", 1))
        self.assertIsNone(self._deadline(None, 1))


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """假 httpx client：按 postId 返回 listPositionDetail 响应，记录调用。"""

    def __init__(self, by_postid):
        self.by = by_postid
        self.calls = []

    def post(self, url, data=None, **kwargs):
        self.calls.append((url, data))
        pid = (data or {}).get("postId")
        return _FakeResp(self.by.get(pid, {"data": {}}))


class TestHotJobDetailEnrich(unittest.TestCase):
    """P3 富化：列表无 JD 正文，逐岗 listPositionDetail 补 workContent/serviceCondition → summary。"""

    def setUp(self):
        self.a = HotJobAdapter()
        self.a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html")

    def test_enrich_fills_jd_fields_then_map_builds_summary(self):
        posts = [
            {"postId": "p1", "postName": "后端工程师", "workPlaceStr": "上海市"},
            {"postId": "p2", "postName": "前端工程师", "workPlaceStr": "北京市"},
        ]
        client = _FakeClient({
            "p1": {"data": {"workContent": "负责服务端开发", "serviceCondition": "本科及以上"}},
            "p2": {"data": {"workContent": "负责前端开发"}},
        })
        self.a._enrich_details(client, posts)
        # 并发补全 → 调用顺序不确定，按集合校验（详情 API 路径 + 覆盖到 p1/p2，body 带 recruitType）
        self.assertTrue(all(url.endswith(
            "/wecruit/positionInfo/listPositionDetail/SU64893571bef57c16d356b99e")
            for url, _ in client.calls))
        self.assertEqual({d["postId"] for _, d in client.calls}, {"p1", "p2"})
        self.assertTrue(all("recruitType" in d for _, d in client.calls))
        # 补回岗位字段 → _map 产出 summary
        self.assertEqual(posts[0]["workContent"], "负责服务端开发")
        job = self.a._map(posts[0])
        self.assertIn("负责服务端开发", job.summary)
        self.assertIn("本科及以上", job.summary)

    def test_enrich_respects_cap_and_skips_missing_postid(self):
        posts = [{"postId": f"p{i}", "postName": "X"} for i in range(50)]
        posts.append({"postName": "无id岗"})  # 无 postId → 跳过，不计入 cap
        client = _FakeClient({f"p{i}": {"data": {"workContent": "j"}} for i in range(50)})
        self.a._DETAIL_CAP = 5
        self.a._enrich_details(client, posts)
        self.assertEqual(len(client.calls), 5)

    def test_enrich_tolerates_detail_failure(self):
        class _Boom:
            def post(self, *a, **k):
                raise RuntimeError("anti-bot 403")
        posts = [{"postId": "p1", "postName": "X"}]
        # 详情失败不抛、不污染：summary 保持 None，岗位仍可入库
        self.a._enrich_details(_Boom(), posts)
        self.assertNotIn("workContent", posts[0])
        self.assertIsNone(self.a._map(posts[0]).summary)


class TestHotJobChannelGate(unittest.TestCase):
    """should_skip() 两道门 —— 不打真实网络，按接口分派构造响应。

    门 1 门户存在（suite/config 有无站点配置键）；门 2 渠道发布（search/condition 有无 data）。
    2026-08-26 / 2026-09-05 live 实测：两种坏法下 listPosition 都照常返回岗位，
    只有这两道门能把「抓得到但用户点不开」的死链挡在入库之前。
    """

    # 门 1 通过所需的最小 config（真实响应里还有 companyName 等，判据只看站点配置键）
    GOOD_CFG = {"data": {"companyName": "X", "websiteTitlePicUrl": "{}", "keywords": "X招聘"}}
    # 整站被下掉：data 还在、基础信息还在，但没有任何站点配置键
    DEAD_CFG = {"data": {"companyName": "X", "suitOrgInfoPOs": [], "recruitTypeNameMap": {}}}
    GOOD_COND = {"data": {"searchDisplayItem": [{"value": "workPlace"}]}, "state": "200"}
    UNPUB_COND = {"state": "200", "type": "success"}

    def setUp(self):
        self.a = HotJobAdapter()
        self.url = "https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/social.html"

    def _patch(self, cfg=None, cond=None, boom=None):
        """按接口分派：config 走 cfg、condition 走 cond。默认两道门都放行。"""
        calls = []
        cfg = self.GOOD_CFG if cfg is None else cfg
        cond = self.GOOD_COND if cond is None else cond

        class _Resp:
            def __init__(self_inner, payload):
                self_inner._payload = payload

            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return self_inner._payload

        def fake_get(api, **kwargs):
            calls.append((api, kwargs.get("params")))
            if boom:
                raise boom
            return _Resp(cfg if "/suite/config/" in api else cond)

        orig_get = hotjob_mod.httpx.get
        hotjob_mod.httpx.get = fake_get
        self.addCleanup(lambda: setattr(hotjob_mod.httpx, "get", orig_get))
        return calls

    # ---- 门 2：渠道发布 ----

    def test_skips_channel_whose_portal_is_unpublished(self):
        calls = self._patch(cond=self.UNPUB_COND)
        reason = self.a.should_skip(self.url)
        self.assertIsNotNone(reason)
        self.assertIn("recruitType=2", reason)
        cond_calls = [c for c in calls if "/search/condition/" in c[0]]
        self.assertIn("condition/SU630dafb40dcad4076dfdf5ce", cond_calls[0][0])
        self.assertEqual(cond_calls[0][1], {"recruitType": 2})

    def test_does_not_skip_when_channel_published(self):
        self._patch()
        self.assertIsNone(self.a.should_skip(self.url))

    def test_probes_channel_specific_recruit_type(self):
        calls = self._patch(cond=self.UNPUB_COND)
        a = HotJobAdapter()
        a.should_skip("https://seazen.hotjob.cn/SU630dafb40dcad4076dfdf5ce/pb/interns.html")
        cond_calls = [c for c in calls if "/search/condition/" in c[0]]
        self.assertEqual(cond_calls[0][1], {"recruitType": 12})

    # ---- 门 1：门户存在 ----

    def test_skips_tenant_whose_portal_no_longer_exists(self):
        """整站被下掉：config 无站点配置键 → 跳过。

        ⚠️ 关键回归：这种租户的 condition **是过门 2 的**（GOOD_COND），
        所以门 2 拦不住它 —— 2026-09-05 实测 7 个租户 993 个 active 死链正是这么进来的。
        """
        self._patch(cfg=self.DEAD_CFG, cond=self.GOOD_COND)
        reason = self.a.should_skip(self.url)
        self.assertIsNotNone(reason)
        self.assertIn("portal does not exist", reason)

    def test_portal_gate_probes_suite_config(self):
        calls = self._patch(cfg=self.DEAD_CFG)
        self.a.should_skip(self.url)
        self.assertIn("/wecruit/suite/config/SU630dafb40dcad4076dfdf5ce", calls[0][0])

    def test_portal_gate_accepts_any_single_site_key(self):
        """三个站点配置键**任一**存在即算配过站（各租户配置项不同，不能要求全有）。"""
        for key in ("websiteTitlePicUrl", "keywords", "description"):
            with self.subTest(key=key):
                a = HotJobAdapter()
                self._patch(cfg={"data": {"companyName": "X", key: "v"}})
                self.assertIsNone(a.should_skip(self.url))

    def test_portal_gate_skips_when_data_missing_entirely(self):
        self._patch(cfg={"state": "200", "type": "success"})
        self.assertIsNotNone(self.a.should_skip(self.url))

    # ---- 共同：探测失败一律放行 ----

    def test_probe_failure_does_not_block_crawl(self):
        # 宁可漏判不可错杀：探测本身失败（网络/限流）不许把好源判死
        self._patch(boom=RuntimeError("network down"))
        self.assertIsNone(self.a.should_skip(self.url))


class _ListServer:
    """照 2026-10-10 实测的平台行为回放 listPosition：第 1 页每页几条由对方定（first_page_size），
    不听请求里的 pageSize；第 2 页起听请求的 pageSize。每个响应的 totalPage 按它自己的页长算。"""
    total, first_page_size, fail_gap = 72, 12, False
    requests = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, data=None, **kwargs):
        cls = type(self)
        if "postId" in data:   # 逐岗详情
            return _FakeResp({"data": {"workContent": "正文-" + data["postId"]}})
        page, asked = int(data["currentPage"]), int(data["pageSize"])
        cls.requests.append((page, asked))
        if cls.fail_gap and page > 1 and asked != 20:
            raise OSError("connection reset")
        size = cls.first_page_size if page == 1 else asked
        rows = [{"postId": f"p{i}", "postName": f"岗{i}"}
                for i in range((page - 1) * size, min(page * size, cls.total))]
        return _FakeResp({"data": {"pageForm": {
            "pageData": rows, "pageSize": size, "currentPage": page, "dataCount": cls.total,
            "totalPage": -(-cls.total // size)}}})


class TestHotJobFirstPage(unittest.TestCase):
    """第 1 页回多少条一页、totalPage 按哪种页长算都由对方定，不听我们传的 pageSize（2026-10-10 立）。

    live：财通证券校招第 1 页恒回 12 条（传 20 / 15 / 10 / 不传都一样），第 2 页从第 21 条起 →
    第 13~20 条取不到，72 个岗拿到 64 个还记抓全；中国物流集团社招第 1 页回 50 条一页、totalPage=3，
    按 20 条一页翻 3 页就停，115 个岗拿到 60 个还记抓全。"""

    def _fetch(self, detail_cap="0", **server):
        _ListServer.total, _ListServer.first_page_size, _ListServer.fail_gap = 72, 12, False
        for key, value in server.items():
            setattr(_ListServer, key, value)
        _ListServer.requests = []
        orig_client, orig_cap = hotjob_mod.httpx.Client, os.environ.get("CRAWL_DETAIL_CAP")
        hotjob_mod.httpx.Client = _ListServer
        os.environ["CRAWL_DETAIL_CAP"] = detail_cap   # "0" = 只测列表翻页
        try:
            a = HotJobAdapter()
            raw = a.fetch("https://wecruit.hotjob.cn/SU60613f74bef57c36adc66d0b/pb/school.html")
        finally:
            hotjob_mod.httpx.Client = orig_client
            if orig_cap is None:
                del os.environ["CRAWL_DETAIL_CAP"]
            else:
                os.environ["CRAWL_DETAIL_CAP"] = orig_cap
        rows = [r for payload in json.loads(raw)["_intercepted"]
                for r in payload["data"]["pageForm"]["pageData"]]
        return a, rows

    def test_gap_between_first_and_second_page_is_filled(self):
        a, rows = self._fetch()
        ids = [r["postId"] for r in rows]
        self.assertEqual(set(ids), {f"p{i}" for i in range(72)}, "第 13~20 条不能断档")
        self.assertEqual(len(ids), 72, "补的那页与第 2 页重叠的 4 条（第 21~24 条）在信封里只能有一份")
        self.assertEqual(a.reported_total, 72)
        self.assertTrue(a.fetch_complete)

    def test_original_requests_are_kept_and_only_the_fill_is_added(self):
        """按 20 条一页的各页照旧要、只在后面多补一页 → 拿到的岗只多不少（大租户不会因页变小而翻不完）。"""
        self._fetch()
        self.assertEqual(_ListServer.requests, [(1, 20), (2, 20), (3, 20), (4, 20), (2, 12)])

    def test_tiny_first_page_needs_several_fill_pages(self):
        a, rows = self._fetch(total=50, first_page_size=6)
        self.assertEqual([r for r in _ListServer.requests if r[1] == 6], [(2, 6), (3, 6), (4, 6)])
        self.assertEqual(len({r["postId"] for r in rows}), 50)
        self.assertEqual(len(rows), 50)
        self.assertTrue(a.fetch_complete)

    def test_first_page_total_page_is_not_trusted(self):
        """第 1 页被回成 50 条一页时自报 totalPage=3；按它停，20 条一页只翻到第 60 条。"""
        a, rows = self._fetch(total=115, first_page_size=50)
        self.assertEqual(_ListServer.requests, [(page, 20) for page in range(1, 7)], "没有断档，不多发请求")
        self.assertEqual(len({r["postId"] for r in rows}), 115)
        self.assertEqual(a.reported_total, 115)
        self.assertTrue(a.fetch_complete)

    def test_no_fill_request_when_there_is_no_gap(self):
        cases = {"按 20 条一页回": dict(total=42, first_page_size=20),
                 "一页没装满": dict(total=9, first_page_size=12),
                 "一页正好装满": dict(total=12, first_page_size=12)}
        for name, server in cases.items():
            with self.subTest(name):
                a, rows = self._fetch(**server)
                self.assertTrue(all(asked == 20 for _, asked in _ListServer.requests))
                if server["total"] <= server["first_page_size"]:
                    self.assertEqual(_ListServer.requests, [(1, 20)], "一页装完的源不该多发请求")
                self.assertEqual(len(rows), server["total"])
                self.assertEqual(a.reported_total, server["total"])
                self.assertTrue(a.fetch_complete)

    def test_unfilled_gap_is_not_reported_as_complete(self):
        """补的那页没要到：照样交出已拿到的岗，但去重后不够 dataCount → 不许记抓全。"""
        a, rows = self._fetch(fail_gap=True)
        self.assertEqual(len(rows), 64)
        self.assertEqual(a.reported_total, 72)
        self.assertFalse(a.fetch_complete)

    def test_filled_rows_get_their_detail_text_like_first_page_rows(self):
        """逐岗补正文只补前 N 个：补回来的第 13~20 条排在第 1 页后面，不能总被挤到名额外。"""
        _, rows = self._fetch(detail_cap="20")
        self.assertEqual({r["postId"] for r in rows if r.get("workContent")}, {f"p{i}" for i in range(20)})


if __name__ == "__main__":
    unittest.main()
