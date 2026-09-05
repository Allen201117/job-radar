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


if __name__ == "__main__":
    unittest.main()
