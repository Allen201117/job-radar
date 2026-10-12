"""字节 httpx 全量抓取单测（mock httpx，不打真实网络）。"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters import bytedance as bt
from adapters.bytedance import BytedanceAdapter, BytedanceCampusAdapter, BytedanceGlobalAdapter


def _post(pid, *, category_id="cat_a", parent_id=None, city_code="CT_11", city="北京"):
    parent = {"id": parent_id, "name": "研发"} if parent_id else None
    return {
        "id": str(pid),
        "title": f"岗位{pid}",
        "city_list": [{"code": city_code, "name": city}],
        "job_category": {"id": category_id, "name": "后端", "parent": parent},
        "description": "负责系统设计",
        "requirement": "熟悉 Python",
        "recruit_type": {"parent": {"name": "社会招聘"}, "name": "正式"},
        "publish_time": 1782864000000,
    }


class MappingTest(unittest.TestCase):
    def test_social_field_map_uses_list_body_and_experienced_url(self):
        adapter = BytedanceAdapter()

        job = adapter._map(_post("7657467065993218309"))

        self.assertEqual(job.company, "字节跳动")
        self.assertEqual(job.location, "北京")
        self.assertEqual(job.job_type, "社招")
        self.assertIn("负责系统设计", job.summary)
        self.assertIn("熟悉 Python", job.summary)
        self.assertEqual(job.posted_at, "2026-07-01")
        self.assertEqual(
            job.jd_url,
            "https://jobs.bytedance.com/experienced/position/7657467065993218309/detail",
        )
        ok, reason = normalizer.validate_job_quality(
            job, "https://jobs.bytedance.com/experienced/position"
        )
        self.assertTrue(ok, reason)

    def test_campus_intern_field_map_uses_campus_url_and_recruit_type(self):
        adapter = BytedanceCampusAdapter()
        post = _post("7657467065993218310")
        post["recruit_type"] = {"parent": {"name": "校园招聘"}, "name": "暑期实习"}

        job = adapter._map(post)

        self.assertEqual(job.job_type, "暑期实习")
        self.assertEqual(
            job.jd_url,
            "https://jobs.bytedance.com/campus/position/7657467065993218310/detail",
        )

    def test_job_type_falls_back_to_track_not_category_name_when_recruit_type_unknown(self):
        post = _post("7657467065993218311")
        post["recruit_type"] = {"parent": {"name": ""}, "name": "正式"}

        social = BytedanceAdapter()._map(post)
        campus = BytedanceCampusAdapter()._map(post)

        self.assertEqual(social.job_type, "社招")
        self.assertEqual(campus.job_type, "校招")
        self.assertNotEqual(social.job_type, "后端")
        self.assertNotEqual(campus.job_type, "后端")
        self.assertNotEqual(social.job_type, "正式")
        self.assertNotEqual(campus.job_type, "正式")


class TrackPlanningTest(unittest.TestCase):
    def test_reconcile_complete_compares_parent_total_to_covered_counts(self):
        self.assertTrue(bt.reconcile_complete(10, [4, 6]))
        self.assertTrue(bt.reconcile_complete(10, [7, 6]))
        self.assertFalse(bt.reconcile_complete(10, [4, 5]))

    def test_direct_count_under_cap_pages_without_slicing(self):
        calls = []

        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            calls.append((rid, offset, limit, category_id, city_code))
            rows = [_post(i) for i in range(offset, min(offset + limit, 5))]
            return bt.BytedancePage(count=5, jobs=rows)

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["0", "1", "2", "3", "4"])
        self.assertTrue(result.complete)
        self.assertTrue(all(call[3] is None and call[4] is None for call in calls))

    def test_capped_count_uses_category_then_city_and_dedups_ids(self):
        calls = []

        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            calls.append((rid, offset, limit, category_id, city_code))
            key = (category_id, city_code, offset, limit)
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=4, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=4,
                    jobs=[
                        _post("seed-a", parent_id="cat_a"),
                        _post("seed-b", parent_id="cat_b"),
                    ],
                )
            if key == ("cat_a", None, 0, 1):
                return bt.BytedancePage(count=2, jobs=[_post("1", parent_id="cat_a")])
            if key == ("cat_a", None, 0, 2):
                return bt.BytedancePage(
                    count=2, jobs=[_post("1", parent_id="cat_a"), _post("2", parent_id="cat_a")]
                )
            if key == ("cat_b", None, 0, 1):
                return bt.BytedancePage(count=4, jobs=[_post("2", parent_id="cat_b")])
            if key == ("cat_b", None, 0, 2):
                return bt.BytedancePage(
                    count=4,
                    jobs=[
                        _post("2", parent_id="cat_b", city_code="CT_11"),
                        _post("3", parent_id="cat_b", city_code="CT_31", city="上海"),
                    ],
                )
            if key == ("cat_b", "CT_11", 0, 1):
                return bt.BytedancePage(count=2, jobs=[_post("2", parent_id="cat_b")])
            if key == ("cat_b", "CT_11", 0, 2):
                return bt.BytedancePage(
                    count=2, jobs=[_post("2", parent_id="cat_b"), _post("4", parent_id="cat_b")]
                )
            if key == ("cat_b", "CT_31", 0, 1):
                return bt.BytedancePage(
                    count=2,
                    jobs=[_post("3", parent_id="cat_b", city_code="CT_31", city="上海")],
                )
            if key == ("cat_b", "CT_31", 0, 2):
                return bt.BytedancePage(
                    count=2,
                    jobs=[
                        _post("3", parent_id="cat_b", city_code="CT_31", city="上海"),
                        _post("5", parent_id="cat_b", city_code="CT_31", city="上海"),
                    ],
                )
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["1", "2", "4", "3", "5"])
        self.assertTrue(result.complete)
        self.assertIn(("1", 0, 1, "cat_b", None), calls)
        self.assertIn(("1", 0, 1, "cat_b", "CT_11"), calls)
        self.assertIn(("1", 0, 1, "cat_b", "CT_31"), calls)

    def test_category_sample_undercoverage_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[_post("seed-a1", parent_id="cat_a"), _post("seed-a2", parent_id="cat_a")],
                )
            if category_id == "cat_a" and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=8, jobs=[_post("0", parent_id="cat_a")])
                rows = [_post(i, parent_id="cat_a") for i in range(offset, min(offset + limit, 8))]
                return bt.BytedancePage(count=8, jobs=rows)
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=10
        )

        self.assertEqual(len(result.jobs), 8)
        self.assertFalse(result.complete)

    def test_city_sample_undercoverage_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            if category_id is None and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("seed", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[_post("seed-a1", parent_id="cat_a"), _post("seed-a2", parent_id="cat_a")],
                )
            if category_id == "cat_a" and city_code is None:
                if limit == 1:
                    return bt.BytedancePage(count=12, jobs=[_post("0", parent_id="cat_a")])
                return bt.BytedancePage(
                    count=12,
                    jobs=[
                        _post("city-seed-1", parent_id="cat_a", city_code="CT_11"),
                        _post("city-seed-2", parent_id="cat_a", city_code="CT_11"),
                    ],
                )
            if category_id == "cat_a" and city_code == "CT_11":
                if limit == 1:
                    return bt.BytedancePage(count=8, jobs=[_post("0", parent_id="cat_a")])
                rows = [_post(i, parent_id="cat_a") for i in range(offset, min(offset + limit, 8))]
                return bt.BytedancePage(count=8, jobs=rows)
            return bt.BytedancePage(count=0, jobs=[])

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=20, sample_limit=2, count_cap=10
        )

        self.assertEqual(len(result.jobs), 8)
        self.assertFalse(result.complete)

    def test_safety_cap_stops_and_marks_incomplete(self):
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            rows = [_post(i) for i in range(offset, min(offset + limit, 5))]
            return bt.BytedancePage(count=5, jobs=rows)

        result = bt.collect_bytedance_track(
            fake_fetch, "1", page_limit=2, max_jobs=3, sample_limit=4
        )

        self.assertEqual([p["id"] for p in result.jobs], ["0", "1", "2"])
        self.assertFalse(result.complete)
        self.assertTrue(result.hit_max_jobs)


class RetryTest(unittest.TestCase):
    def test_405_retries_after_backoff_without_crashing(self):
        adapter = BytedanceAdapter()
        adapter.request_interval_s = 0
        adapter.retry_backoff_s = 0
        adapter.max_retries = 3
        calls = []

        class Resp:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        class Client:
            def post(self, url, json=None):
                calls.append((url, json))
                if len(calls) == 1:
                    return Resp(405, {})
                return Resp(200, {"data": {"count": 1, "job_post_list": [_post("1")]}})

        page = adapter._request_page(Client(), {"keyword": "", "limit": 1, "offset": 0})

        self.assertEqual(page.count, 1)
        self.assertEqual(len(page.jobs), 1)
        self.assertEqual(len(calls), 2)


class _Resp:
    def __init__(self, payload, status_code=200):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _FakeClient:
    """假 httpx.Client：按「请求带的 website-path」决定回什么，并记下每次请求。"""

    def __init__(self, *, probe_payload, filters_payload, list_payload):
        self.probe_payload = probe_payload
        self.filters_payload = filters_payload
        self.list_payload = list_payload
        self.posts = []
        self.gets = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        self.posts.append((json, headers))
        if headers and headers.get("website-path") == bt._PROBE_WEBSITE_PATH:
            return _Resp(self.probe_payload)
        return _Resp(self.list_payload)

    def get(self, url):
        self.gets.append(url)
        return _Resp(self.filters_payload)


_SITE_NOT_EXIST = {"code": -9000003, "message": "site not exist", "data": None}
_FILTERS = {"code": 0, "data": {"job_type_list": [{"id": "cat_a", "name": "研发"}]}}


def _run_httpx_fetch(adapter, client, made=None):
    """made（可选 dict）收下 httpx.Client(...) 被调用时的参数，用来核「列表请求默认带哪个门户头」。"""
    adapter.request_interval_s = 0
    adapter.retry_backoff_s = 0
    with mock.patch.object(bt.httpx, "Client", return_value=client) as factory:
        try:
            return adapter._httpx_fetch()
        finally:
            if made is not None:
                made.update(factory.call_args.kwargs)


class PortalHeaderTest(unittest.TestCase):
    """每条源只取自己那个公开门户（2026-10-12 全集对拍：不带头的列表不是任何公开门户的列表）。"""

    def test_each_source_sends_its_own_portal(self):
        self.assertEqual(BytedanceAdapter()._headers()["website-path"], "society")
        self.assertEqual(BytedanceCampusAdapter()._headers()["website-path"], "campus")
        self.assertEqual(BytedanceGlobalAdapter()._headers()["website-path"], "en")

    def test_referral_portal_is_never_requested(self):
        # robots.txt：Disallow /referral。任何一条源、探针都不许用它。
        for cls in (BytedanceAdapter, BytedanceCampusAdapter, BytedanceGlobalAdapter):
            self.assertNotEqual(cls.website_path, "referral")
        self.assertNotEqual(bt._PROBE_WEBSITE_PATH, "referral")

    def test_global_portal_takes_all_recruitment_types(self):
        self.assertEqual(BytedanceGlobalAdapter.recruitment_id, "")
        client = _FakeClient(
            probe_payload=_SITE_NOT_EXIST, filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        _run_httpx_fetch(BytedanceGlobalAdapter(), client)
        self.assertTrue(client.posts)
        self.assertTrue(all(body["recruitment_id_list"] == [] for body, _ in client.posts))

        client = _FakeClient(
            probe_payload=_SITE_NOT_EXIST, filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        _run_httpx_fetch(BytedanceCampusAdapter(), client)
        self.assertTrue(all(body["recruitment_id_list"] == ["2"] for body, _ in client.posts))

    def test_probe_ok_and_list_fetched_with_real_portal(self):
        client = _FakeClient(
            probe_payload=_SITE_NOT_EXIST, filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        made = {}
        result = _run_httpx_fetch(BytedanceAdapter(), client, made)

        self.assertTrue(result.complete)
        self.assertEqual([p["id"] for p in result.jobs], ["1"])
        # 列表请求走 Client 的默认头：必须是这条源自己的门户；只有探针那一次单独换成假门户名。
        self.assertEqual(made["headers"]["website-path"], "society")
        per_request = [h for _, h in client.posts if h]
        self.assertEqual(per_request, [{"website-path": bt._PROBE_WEBSITE_PATH}])
        self.assertGreaterEqual(len([1 for _, h in client.posts if not h]), 2)   # 根探测 + 列表页
        self.assertEqual(client.gets, [])   # 根列表没封顶：不需要职类清单，不白打一次配置接口

    def test_header_ignored_fails_the_run_instead_of_writing(self):
        # 不存在的门户也回了岗位 = 头被无视 = 取到的是「不带头」那份列表：必须抛错，不许写库。
        client = _FakeClient(
            probe_payload={"code": 0, "data": {"count": 9, "job_post_list": [_post("ghost")]}},
            filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        with self.assertRaises(RuntimeError):
            _run_httpx_fetch(BytedanceAdapter(), client)
        self.assertEqual(len([1 for _, h in client.posts if not h]), 0)   # 一条列表请求都没发

    def test_probe_inconclusive_twice_fails_the_run(self):
        # 探针问不到结果，就没法确认这一轮取到的是哪份列表：再问一次，还问不到就整轮不写。
        client = _FakeClient(
            probe_payload={"code": 500, "message": "busy", "data": None}, filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        with self.assertRaises(RuntimeError):
            _run_httpx_fetch(BytedanceAdapter(), client)
        self.assertEqual(len([1 for _, h in client.posts if h]), 2)
        self.assertEqual(len([1 for _, h in client.posts if not h]), 0)

    def test_probe_recovers_on_second_ask(self):
        class Flaky(_FakeClient):
            def post(self, url, json=None, headers=None):
                is_probe = bool(headers) and headers.get("website-path") == bt._PROBE_WEBSITE_PATH
                if is_probe and not any(h for _, h in self.posts):
                    self.posts.append((json, headers))
                    raise RuntimeError("connection reset")
                return super().post(url, json=json, headers=headers)

        client = Flaky(
            probe_payload=_SITE_NOT_EXIST, filters_payload=_FILTERS,
            list_payload={"code": 0, "data": {"count": 1, "job_post_list": [_post("1")]}},
        )
        result = _run_httpx_fetch(BytedanceAdapter(), client)

        self.assertTrue(result.complete)
        self.assertEqual(len(result.jobs), 1)


def _capped_fetch(sample_parent="cat_a"):
    """根列表封顶（count == count_cap = 4）的假接口：采样只见 sample_parent；cat_a 2 岗、cat_b 1 岗。"""
    def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
        if category_id is None:
            return bt.BytedancePage(count=4, jobs=[_post("s1", parent_id=sample_parent),
                                                   _post("s2", parent_id=sample_parent)])
        if category_id == "cat_a":
            return bt.BytedancePage(count=2, jobs=[_post("1", parent_id="cat_a"), _post("2", parent_id="cat_a")])
        if category_id == "cat_b":
            return bt.BytedancePage(count=1, jobs=[_post("9", parent_id="cat_b")])
        if category_id == "cat_x":
            return bt.BytedancePage(count=1, jobs=[_post("7", parent_id="cat_x")])
        return bt.BytedancePage(count=0, jobs=[])
    return fake_fetch


_CAPPED_KW = dict(page_limit=2, max_jobs=50, sample_limit=2, count_cap=4)


class CompletenessTest(unittest.TestCase):
    def test_category_list_is_only_fetched_when_root_is_capped(self):
        calls = []

        def provider():
            calls.append(1)
            return ["cat_a"]

        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            return bt.BytedancePage(count=2, jobs=[_post(i) for i in range(offset, min(offset + limit, 2))])

        result = bt.collect_bytedance_track(fake_fetch, "2", page_limit=2, max_jobs=20, sample_limit=4,
                                            category_ids_provider=provider)
        self.assertTrue(result.complete)
        self.assertEqual(calls, [])

    def test_capped_root_without_portal_category_list_is_not_complete(self):
        # 根 count 封顶时「各职类之和 ≥ 根 count」恒成立，只靠采样漏一个小职类发现不了。
        result = bt.collect_bytedance_track(_capped_fetch(), "1", category_ids_provider=lambda: [], **_CAPPED_KW)

        self.assertEqual(sorted(p["id"] for p in result.jobs), ["1", "2"])   # 照常收采样到的那一类
        self.assertFalse(result.complete)

    def test_sampled_category_outside_portal_list_is_not_complete(self):
        # 采样到了清单里没有的职类 = 清单不是全集：那一类照收，但这一轮不许拿去判缺席。
        result = bt.collect_bytedance_track(_capped_fetch("cat_x"), "1",
                                            category_ids_provider=lambda: ["cat_a", "cat_b"], **_CAPPED_KW)

        self.assertEqual(sorted(p["id"] for p in result.jobs), ["1", "2", "7", "9"])
        self.assertFalse(result.complete)
    def test_leaf_short_of_reported_count_is_not_complete(self):
        # 自报 5、翻完只拿到 4 个不同编号（翻页期间对方上下架，行跨页挪位）→ 不许拿去判缺席。
        def fake_fetch(rid, offset, limit, category_id=None, city_code=None):
            ids = [0, 1, 2, 3, 3][offset:offset + limit]
            return bt.BytedancePage(count=5, jobs=[_post(i) for i in ids])

        result = bt.collect_bytedance_track(fake_fetch, "2", page_limit=2, max_jobs=20, sample_limit=4)

        self.assertEqual(len(result.jobs), 4)
        self.assertFalse(result.complete)

    def test_portal_category_list_covers_what_sampling_missed(self):
        # 采样的前几条全是 cat_a；cat_b 只在门户自报的职类清单里——没有清单就整类漏掉。
        without = bt.collect_bytedance_track(_capped_fetch(), "1", **_CAPPED_KW)
        with_list = bt.collect_bytedance_track(_capped_fetch(), "1",
                                               category_ids_provider=lambda: ["cat_a", "cat_b"], **_CAPPED_KW)

        self.assertNotIn("9", [p["id"] for p in without.jobs])
        self.assertIn("9", [p["id"] for p in with_list.jobs])


def _global_post(pid, en_name, zh_name, *, parent="社招", name="正式"):
    post = _post(pid)
    post["title"] = f"Software Engineer {pid}"
    post["city_list"] = [{"code": "CT_1", "name": zh_name, "en_name": en_name}]
    post["recruit_type"] = {"parent": {"name": parent}, "name": name}
    return post


class GlobalSiteTest(unittest.TestCase):
    """全球站 joinbytedance.com：链接、地点口径、地区白名单。"""

    def _adapter(self):
        adapter = BytedanceGlobalAdapter()
        adapter.regions = {"CN", "US", "SG", "Remote"}
        return adapter

    def test_link_points_to_global_site_and_passes_quality_gate(self):
        job = self._adapter()._map(_global_post("7509262740803930376", "San Jose", "圣何塞"))

        self.assertEqual(job.jd_url, "https://joinbytedance.com/search/7509262740803930376")
        self.assertEqual(job.location, "San Jose")
        self.assertEqual(job.job_type, "社招")
        ok, reason = normalizer.validate_job_quality(job, "https://joinbytedance.com/search")
        self.assertTrue(ok, reason)

    def test_type_comes_from_each_post_not_from_the_source(self):
        adapter = self._adapter()
        self.assertEqual(adapter._map(_global_post("1", "Seattle", "西雅图", parent="校招", name="实习")).job_type, "实习")
        self.assertEqual(adapter._map(_global_post("2", "Seattle", "西雅图", parent="校招", name="正式")).job_type, "校招")

    def test_english_city_name_decides_country(self):
        # 中文名「圣地亚哥」会被判成智利；这个岗在 San Diego。
        adapter = self._adapter()
        job = adapter._map(_global_post("3", "San Diego", "圣地亚哥"))
        row = normalizer.normalize(job, source_id="s", company="字节跳动", regions=adapter.regions)

        self.assertEqual(row["country_code"], "US")
        self.assertEqual(row["job_scope"], "overseas")

    def test_only_whitelisted_regions_are_kept(self):
        adapter = self._adapter()
        kept = {en: adapter._map(_global_post(str(i), en, zh)) is not None for i, (en, zh) in enumerate([
            ("Singapore", "新加坡"), ("Seattle", "西雅图"), ("Hong Kong (China)", "中国香港"),
            ("Tokyo", "东京"), ("London", "伦敦"), ("Taguig", "塔吉格"),
        ])}

        self.assertEqual(kept, {"Singapore": True, "Seattle": True, "Hong Kong (China)": True,
                                "Tokyo": False, "London": False, "Taguig": False})

    def test_chinese_sites_do_not_filter_by_region(self):
        # 中文站门户本身就是国内口径，不许因为加了地区过滤把存量行为改掉。
        adapter = BytedanceAdapter()
        adapter.regions = {"CN"}
        self.assertIsNotNone(adapter._map(_post("1", city="新加坡")))


class SharedRateLimitTest(unittest.TestCase):
    def test_sources_share_one_rate_limit(self):
        # 三条源打同一个接口主机、同一个出口 IP；全球站的 source_url 在另一个域名上，run.py 会让它和另外两条并行。
        # 各限各的速 = 合起来双倍频率，所以间隔必须跨实例生效。
        first, second = BytedanceAdapter(), BytedanceGlobalAdapter()
        first.request_interval_s = second.request_interval_s = 5.0
        slept = []
        with mock.patch.object(bt, "_LAST_REQUEST_AT", [None]), \
                mock.patch.object(bt.time, "sleep", side_effect=slept.append):
            first._wait_for_rate_limit()
            second._wait_for_rate_limit()

        self.assertEqual(len(slept), 1)
        self.assertGreater(slept[0], 4.0)


class FetchEnvelopeTest(unittest.TestCase):
    def test_fetch_sets_complete_only_when_track_complete(self):
        adapter = BytedanceAdapter()
        rows = [_post("1")]
        result = bt.BytedanceFetchResult(jobs=rows, total=1, complete=True)
        with mock.patch.object(adapter, "_httpx_fetch", return_value=result):
            out = json.loads(adapter.fetch("https://jobs.bytedance.com/experienced/position"))

        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(out["_intercepted"][0]["data"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
