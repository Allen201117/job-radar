import json
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

import httpx

import normalizer
from adapters import byd as mod
from adapters.byd import BydAdapter, BydCampusAdapter, _list_offsets


class _StubResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class _StubClient:
    """记录 queryDetail 调用、按 id 返回带 tagDetailList 的 detail（模拟公开接口，不打网络）。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json):  # noqa: A002 (匹配 httpx.Client.post 关键字签名)
        jid = json["id"]
        self.calls.append(jid)
        return _StubResp({"id": jid, "positionName": f"岗位{jid}",
                          "tagDetailList": [{"name": "工作职责", "detail": "x"}]})


class BydAdapterTest(unittest.TestCase):
    def test_list_offsets_use_api_row_offsets_not_page_numbers(self):
        self.assertEqual(_list_offsets(total=2163, page_size=1000), [0, 1000, 2000])
        self.assertEqual(_list_offsets(total=999, page_size=1000), [0])

    def test_parse_only_emits_rows_with_browser_verified_detail_url(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?verified-token"
                ),
                "detail": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "positionTypeId": "003091",
                    "fatherOrgName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "publishTime": "2026-06-05",
                    "tagDetailList": [
                        {"name": "工作职责", "detail": "负责维修车辆顾客接待。"},
                        {"name": "任职要求", "detail": "沟通协调能力强。"},
                    ],
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "比亚迪")
        self.assertEqual(jobs[0].location, "广东省-湛江市")
        self.assertIn("沟通协调能力强", jobs[0].summary)
        self.assertIn("socialPositionDetails?", jobs[0].jd_url)

    def test_parse_keeps_batch_encrypted_list_row_without_detail_enrichment(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?Y1KjFap0IfmxZbvDidhqr7iflfUYCzJDKePomU8QFx4="
                ),
                "row": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "fatherOrgAliasName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "createTime": "2026-06-05 08:49:17",
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "店端服务顾问")
        self.assertEqual(jobs[0].posted_at, "2026-06-05")

    def test_social_job_type_is_the_channel_and_survives_normalize(self):
        """部门名不是招聘类型：填它时 normalizer 会用正文重推（正文有「应届」→ 校招），不带正文的抓取又
        写回部门名，同一行来回变。按渠道填「社招」后，带不带正文都是同一个值。"""
        def parse(detail):
            payload = {"jobs": [{
                "jd_url": "https://job.byd.com/portal/pc/#/social/socialPositionDetails?verified-token",
                "row": {"id": "1", "positionName": "设备工程师", "orgAliasName": "2部",
                        "province": "广东省", "city": "深圳市"},
                "detail": detail,
            }]}
            return BydAdapter().parse(json.dumps(payload, ensure_ascii=False))[0]

        with_body = parse({"tagDetailList": [
            {"name": "任职要求", "detail": "工作经验：应届硕士生/本科2年/大专3年以上相关工作经验"}]})
        without_body = parse({})
        for raw in (with_body, without_body):
            self.assertEqual(raw.job_type, "社招")
            row = normalizer.normalize(raw, source_id="s", company="比亚迪")
            self.assertEqual(row["job_type"], "社招")


class BydFetchDetailsTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def tearDown(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def test_fetch_details_covers_all_ids_not_capped_at_20(self):
        client = _StubClient()
        ids = [str(i) for i in range(25)]  # >20：旧 DETAIL_CAP=20 只补前 20，现覆盖全量
        details = BydAdapter()._fetch_details(client, ids)
        self.assertEqual(len(details), 25)
        self.assertEqual(sorted(client.calls, key=int), sorted(ids, key=int))
        self.assertEqual(details["7"]["positionName"], "岗位7")

    def test_fetch_details_skipped_when_env_cap_zero(self):
        os.environ["CRAWL_DETAIL_CAP"] = "0"  # 快档：跳过逐岗富化
        details = BydAdapter()._fetch_details(_StubClient(), ["1", "2", "3"])
        self.assertEqual(details, {})

    def test_fetch_details_skips_failed_fetches(self):
        class _FlakyClient(_StubClient):
            def post(self, url, json):
                if json["id"] == "2":
                    raise httpx.HTTPError("boom")  # 单岗失败不阻断整批
                return super().post(url, json)

        details = BydAdapter()._fetch_details(_FlakyClient(), ["1", "2", "3"])
        self.assertEqual(set(details), {"1", "3"})


class _FakePage:
    """假装是官方页面：evaluate 按传入的 path / query 拼一个「密文」，可指定哪些 id 回验失败。"""

    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.evaluate_args = []

    def goto(self, *args, **kwargs):
        pass

    def wait_for_function(self, *args, **kwargs):
        pass

    def evaluate(self, script, arg):
        self.evaluate_args.append((script, arg))
        return [
            [q["id"], None if q["id"] in self.fail_ids
             else f"https://job.byd.com/portal/pc/#{arg['path']}?cipher//{q['id']}"]
            for q in arg["queries"]
        ]


def _fake_playwright(page):
    browser = types.SimpleNamespace(new_page=lambda **kw: page, close=lambda: None)
    pw = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=lambda **kw: browser))

    class _Ctx:
        def __enter__(self):
            return pw

        def __exit__(self, *exc):
            return False

    return types.SimpleNamespace(sync_playwright=lambda: _Ctx())


class BydDetailUrlTest(unittest.TestCase):
    def _generate(self, adapter, ids, fail_ids=()):
        page = _FakePage(fail_ids)
        with mock.patch.dict(sys.modules, {"playwright.sync_api": _fake_playwright(page)}):
            urls = adapter._generate_detail_urls("https://job.byd.com/portal/pc/#/x", ids)
        return urls, page

    def _run_script(self, ids, parse_query):
        """在 node 里真跑页面脚本。假路由照 vue-router 的样子：fullPath 保留密文里的 `//`，href 把它压成 `/`。"""
        harness = (
            "const fn = " + mod._RESOLVE_DETAIL_URLS_JS + ";\n"
            "const router = { options: { parseQuery: " + parse_query + " },\n"
            "  resolve: ({path, query}) => ({ href: '/portal/pc/#' + path + '?ab/' + query.id,\n"
            "                                 route: { fullPath: path + '?ab//' + query.id } }) };\n"
            "globalThis.document = { querySelector: () => ({ __vue__: { $router: router } }) };\n"
            "globalThis.location = { origin: 'https://job.byd.com', pathname: '/portal/pc/' };\n"
            "const queries = " + json.dumps([{"id": i} for i in ids]) + ";\n"
            "process.stdout.write(JSON.stringify(fn({path: '/school/schoolPositionDetail', queries})));\n"
        )
        proc = subprocess.run(["node", "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return dict(json.loads(proc.stdout))

    def test_script_keeps_double_slash_and_checks_the_round_trip(self):
        """route.href 会把密文里的 `//` 压成 `/`（vue-router cleanPath），那样的链接打开是空白页：
        2026-10-11 实测校招 386 条里 6 条、库里社招在招 96 条。脚本回归到 href 这里先红。"""
        urls = self._run_script(["7", "8"], "c => ({ id: c.split('//')[1] })")
        self.assertEqual(urls, {
            "7": "https://job.byd.com/portal/pc/#/school/schoolPositionDetail?ab//7",
            "8": "https://job.byd.com/portal/pc/#/school/schoolPositionDetail?ab//8",
        })

    def test_script_gives_no_url_when_the_site_cannot_decode_it_back(self):
        # 解回的 id 被截短（库里那 96 条坏链接里有 2 条是这样：解得出东西，但不是原来的 id）
        self.assertEqual(self._run_script(["2084113350083"], "c => ({ id: '2084' })"), {"2084113350083": None})
        self.assertEqual(self._run_script(["7"], "c => ({})"), {"7": None})                       # 解不出 id
        self.assertEqual(self._run_script(["7"], "c => { throw new Error('bad') }"), {"7": None})  # 解码器抛错
        self.assertEqual(self._run_script(["7"], "undefined"), {"7": None})                        # 页面没有解码器

    def test_social_and_campus_pass_the_query_the_site_itself_uses(self):
        urls, page = self._generate(BydAdapter(), ["7"])
        self.assertEqual(page.evaluate_args[0][1],
                         {"path": "/social/socialPositionDetails", "queries": [{"id": "7"}]})
        self.assertEqual(urls, {"7": "https://job.byd.com/portal/pc/#/social/socialPositionDetails?cipher//7"})

        _urls, page = self._generate(BydCampusAdapter(), ["9"])
        self.assertEqual(page.evaluate_args[0][1], {
            "path": "/school/schoolPositionDetail",
            "queries": [{"id": "9", "abroad": "", "degree": None}],
        })

    def test_ids_that_fail_the_round_trip_get_no_url(self):
        urls, _page = self._generate(BydAdapter(), ["1", "2", "3"], fail_ids={"2"})
        self.assertEqual(set(urls), {"1", "3"})

    def test_no_ids_does_not_launch_a_browser(self):
        with mock.patch.dict(sys.modules, {"playwright.sync_api": None}):   # 一 import 就炸
            self.assertEqual(BydAdapter()._generate_detail_urls("https://job.byd.com/portal/pc/#/x", []), {})


class BydSocialFetchTest(unittest.TestCase):
    def setUp(self):
        os.environ["CRAWL_DETAIL_CAP"] = "0"

    def tearDown(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def _fetch(self, fail_ids=()):
        rows = [{"id": str(i), "positionName": f"岗位{i}", "province": "广东省", "city": "深圳市"} for i in (1, 2, 3)]

        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, json):  # noqa: A002
                return _StubResp({"total": 3, "data": rows if json["pageNum"] == 0 else []})

        adapter = BydAdapter()

        def fake_urls(source_url, job_ids):
            return {i: f"https://job.byd.com/portal/pc/#/social/socialPositionDetails?c{i}"
                    for i in job_ids if i not in fail_ids}

        with mock.patch.object(mod.httpx, "Client", lambda **kw: _Client()):
            with mock.patch.object(adapter, "_generate_detail_urls", fake_urls):
                html = adapter.fetch("https://job.byd.com/portal/pc/#/social/socialMainPageSocial")
        return adapter, json.loads(html)["jobs"]

    def test_complete_when_every_listed_row_has_a_url(self):
        adapter, jobs = self._fetch()
        self.assertEqual((len(jobs), adapter.reported_total, adapter.fetch_complete), (3, 3, True))

    def test_incomplete_when_a_listed_row_has_no_verified_url(self):
        adapter, jobs = self._fetch(fail_ids={"2"})
        self.assertEqual(sorted(j["row"]["id"] for j in jobs), ["1", "3"])
        self.assertFalse(adapter.fetch_complete)

    def test_no_url_at_all_raises(self):
        with self.assertRaises(RuntimeError):
            self._fetch(fail_ids={"1", "2", "3"})


_ENTRIES = [  # postEntryConfig/list 2026-10-11 的真实形状（顺序也是接口返回的顺序）
    {"postEntryName": "实习生", "batch": "2027", "campusNature": "008502", "abroad": "00112",
     "degree": None, "status": "00111", "sort": 3},
    {"postEntryName": "应届生", "batch": "2027", "campusNature": "008501", "abroad": "00112",
     "degree": None, "status": "00111", "sort": 1},
    {"postEntryName": "外派专项", "batch": "2027", "campusNature": "008501", "abroad": "00111",
     "degree": None, "status": "00111", "sort": 4},
    {"postEntryName": "博士生", "batch": "2027", "campusNature": "008501", "abroad": "00112",
     "degree": "00109", "status": "00111", "sort": 2},
]


def _school_row(job_id, name="高级车身集成工程师", nature="008501", place="深圳市"):
    return {"id": job_id, "jobName": name, "jobType": "研发技术", "workPlace": place,
            "campusNature": nature, "batch": 2027, "updateTime": "2026-09-13"}


class _Resp:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPError("boom")

    def json(self):
        return self._body


class _SchoolClient:
    """按 URL 路由的假 httpx.Client。lists = {招聘性质码: [第 1 页行, 第 2 页行, ...]}，页写 "ERR" = 业务码报错。"""

    def __init__(self, entries=_ENTRIES, lists=None, totals=None, details=None, entry_code=0):
        self.entries, self.entry_code = entries, entry_code
        self.lists = lists or {}
        self.totals = totals or {}
        self.details = details or {}
        self.list_calls, self.detail_calls = [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        if url.endswith("/postEntryConfig/list"):
            return _Resp({"code": self.entry_code, "data": self.entries})
        self.detail_calls.append(params)
        detail = self.details.get(params["id"])
        return _Resp({"code": 0, "data": detail} if detail is not None else {"code": 500, "data": None})

    def post(self, url, json):  # noqa: A002 (匹配 httpx.Client.post 关键字签名)
        self.list_calls.append(json)
        pages = self.lists.get(json["campusNature"], [])
        index = json["pageIndex"] - 1
        rows = pages[index] if index < len(pages) else []
        if rows == "ERR":
            return _Resp({"code": 500, "msg": "系统异常"})
        total = self.totals.get(json["campusNature"], sum(len(p) for p in pages if p != "ERR"))
        return _Resp({"code": 0, "data": rows, "page": {"totalCount": total, "pageIndex": json["pageIndex"]}})


class BydCampusChannelTest(unittest.TestCase):
    def test_channels_come_from_open_entries_deduped_by_batch_and_nature(self):
        """博士生 / 外派专项 是应届生按学历 / 外派筛出来的子集（同届别同性质），不另抓。"""
        channels = BydCampusAdapter()._fetch_channels(_SchoolClient())
        self.assertEqual(channels, [("2027", "008502"), ("2027", "008501")])

    def test_closed_or_unknown_entries_are_not_crawled(self):
        entries = [
            {**_ENTRIES[1], "status": "00112"},                                   # 入口关了
            {**_ENTRIES[0], "campusNature": "008504", "postEntryName": "储干"},   # 不认识的性质：不猜
        ]
        self.assertEqual(BydCampusAdapter()._fetch_channels(_SchoolClient(entries=entries)), [])

    def test_business_error_on_entry_api_raises_instead_of_looking_empty(self):
        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channels(_SchoolClient(entry_code=500))
        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channels(_SchoolClient(entries=None))

    def test_unrecognised_switch_values_are_not_read_as_all_closed(self):
        """开关的字典值变了（既不是「是」也不是「否」）≠ 入口全关。"""
        entries = [{**e, "status": "1"} for e in _ENTRIES]
        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channels(_SchoolClient(entries=entries))

    def test_reported_total_but_no_recognisable_row_raises(self):
        client = _SchoolClient(lists={"008501": [[{"positionId": "1", "jobName": "x"}]]}, totals={"008501": 1})
        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channel_rows(client, "2027", "008501")

    def test_list_request_matches_what_the_school_page_sends(self):
        client = _SchoolClient(lists={"008501": [[_school_row("1")]]})
        BydCampusAdapter()._fetch_channel_rows(client, "2027", "008501")
        self.assertEqual(client.list_calls[0], {
            "topicCode": "", "batch": "2027", "campusNature": "008501", "abroad": "", "degree": "",
            "jobType": [], "researchDirection": [], "workPlace": [], "keywords": "",
            "pageSize": 1000, "pageIndex": 1,
        })

    def test_list_pages_until_reported_total(self):
        client = _SchoolClient(lists={"008501": [[_school_row("1"), _school_row("2")], [_school_row("3")]]})
        rows, total = BydCampusAdapter()._fetch_channel_rows(client, "2027", "008501")
        self.assertEqual((sorted(rows), total), (["1", "2", "3"], 3))
        self.assertEqual([c["pageIndex"] for c in client.list_calls], [1, 2])

    def test_first_page_without_total_raises(self):
        class _NoPage(_SchoolClient):
            def post(self, url, json):  # noqa: A002
                return _Resp({"code": 0, "data": []})   # HTTP 200 + 没有 page：不能当成「没有岗」

        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channel_rows(_NoPage(), "2027", "008501")
        with self.assertRaises(RuntimeError):
            BydCampusAdapter()._fetch_channel_rows(_SchoolClient(lists={"008501": ["ERR"]}), "2027", "008501")

    def test_later_page_failure_keeps_rows_already_fetched(self):
        client = _SchoolClient(lists={"008501": [[_school_row("1")], "ERR"]}, totals={"008501": 2})
        rows, total = BydCampusAdapter()._fetch_channel_rows(client, "2027", "008501")
        self.assertEqual((len(rows), total), (1, 2))


class BydCampusFetchTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def tearDown(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def _fetch(self, client, fail_ids=()):
        adapter = BydCampusAdapter()

        def fake_urls(source_url, job_ids):
            return {i: f"https://job.byd.com/portal/pc/#/school/schoolPositionDetail?c{i}"
                    for i in job_ids if i not in fail_ids}

        with mock.patch.object(mod.httpx, "Client", lambda **kw: client):
            with mock.patch.object(adapter, "_generate_detail_urls", fake_urls):
                html = adapter.fetch("https://job.byd.com/portal/pc/#/school/schoolPositionList")
        return adapter, json.loads(html)["jobs"]

    def _client(self, **kw):
        return _SchoolClient(
            lists={"008501": [[_school_row("1"), _school_row("2")]],
                   "008502": [[_school_row("9", nature="008502")]]},
            details={"1": {"jobName": "高级车身集成工程师", "positionInfoList": []}}, **kw)

    def test_fetch_covers_both_entries_and_judges_completeness_per_entry(self):
        adapter, jobs = self._fetch(self._client())
        self.assertEqual(sorted(j["row"]["id"] for j in jobs), ["1", "2", "9"])
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual({j["row"]["campusNature"] for j in jobs}, {"008501", "008502"})

    def test_same_id_under_two_entries_is_written_once_and_still_complete(self):
        """入口之间有重叠时拿总和当分母会恒判没抓全（小红书 / 华为踩过）→ 逐入口判。"""
        client = _SchoolClient(
            lists={"008501": [[_school_row("1"), _school_row("2")]], "008502": [[_school_row("1")]]},
            details={"1": {"positionInfoList": []}})
        adapter, jobs = self._fetch(client)
        self.assertEqual(sorted(j["row"]["id"] for j in jobs), ["1", "2"])
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)

    def test_later_page_failure_makes_fetch_incomplete(self):
        client = _SchoolClient(
            lists={"008501": [[_school_row("1")], "ERR"], "008502": [[_school_row("9", nature="008502")]]},
            totals={"008501": 2}, details={"1": {"positionInfoList": []}})
        adapter, jobs = self._fetch(client)
        self.assertEqual(sorted(j["row"]["id"] for j in jobs), ["1", "9"])
        self.assertFalse(adapter.fetch_complete)

    def test_rows_that_cannot_be_mapped_fail_loudly_instead_of_looking_empty(self):
        """列表有行、URL 也有，却一行都映射不出岗位（字段改名）：记失败，不能记成「空源、已抓全」。"""
        renamed = {"id": "1", "positionName": "高级车身集成工程师", "workPlace": "深圳市", "campusNature": "008501"}
        client = _SchoolClient(lists={"008501": [[renamed]]}, details={"1": {"positionInfoList": []}})
        with self.assertRaises(RuntimeError):
            self._fetch(client)

    def test_one_unmappable_row_makes_fetch_incomplete(self):
        overseas = _school_row("2", place="新加坡")
        client = _SchoolClient(lists={"008501": [[_school_row("1"), overseas]]},
                               details={"1": {"positionInfoList": []}})
        adapter, jobs = self._fetch(client)
        self.assertEqual(len(adapter.parse(json.dumps({"jobs": jobs}, ensure_ascii=False))), 1)
        self.assertFalse(adapter.fetch_complete)

    def test_heavy_lane_with_no_detail_at_all_raises(self):
        """要补正文却一个详情都没取到 = 详情接口整个坏了；只写标题会是一批没正文的薄卡、状态还是成功。"""
        client = _SchoolClient(lists={"008501": [[_school_row("1"), _school_row("2")]]}, details={})
        with self.assertRaises(RuntimeError):
            self._fetch(client)

    def test_details_ask_for_the_unfiltered_position(self):
        client = self._client()
        self._fetch(client)
        self.assertIn({"id": "1", "abroad": "", "degree": ""}, client.detail_calls)

    def test_a_row_without_verified_url_is_not_written_and_fetch_is_incomplete(self):
        """少写了一个还在列表里的岗时不许标抓全：标了，按缺席下架就会把它当成撤岗。"""
        adapter, jobs = self._fetch(self._client(), fail_ids={"2"})
        self.assertEqual(sorted(j["row"]["id"] for j in jobs), ["1", "9"])
        self.assertFalse(adapter.fetch_complete)

    def test_short_list_is_incomplete(self):
        adapter, _jobs = self._fetch(self._client(totals={"008501": 5}))
        self.assertFalse(adapter.fetch_complete)

    def test_no_open_entry_is_an_empty_season_not_an_error(self):
        adapter, jobs = self._fetch(_SchoolClient(entries=[]))
        self.assertEqual((jobs, adapter.reported_total, adapter.fetch_complete), ([], 0, True))

    def test_rows_but_no_urls_raises(self):
        with self.assertRaises(RuntimeError):
            self._fetch(self._client(), fail_ids={"1", "2", "9"})

    def test_fast_lane_skips_details(self):
        os.environ["CRAWL_DETAIL_CAP"] = "0"
        client = self._client()
        _adapter, jobs = self._fetch(client)
        self.assertEqual(client.detail_calls, [])
        self.assertEqual(len(jobs), 3)

    def test_absence_sweep_stays_dry_run_for_the_new_source(self):
        """校招类声明了按缺席下架，但新源先观察：默认名单里有它，谁在重档开了落库也只打印数字。"""
        import run
        self.assertTrue(BydCampusAdapter.supports_absence_liveness)
        self.assertFalse(getattr(BydAdapter, "supports_absence_liveness", False))
        self.assertIn("byd_campus", run.ABSENCE_OBSERVE_DEFAULT.split(","))
        self.assertIn("beisen", run.ABSENCE_OBSERVE_DEFAULT.split(","))


_SCHOOL_URL = "https://job.byd.com/portal/pc/#/school/schoolPositionDetail?us+yTBA6//7i7h86LCG9di3iZ4sEgB"
_SCHOOL_LIST_URL = "https://job.byd.com/portal/pc/#/school/schoolPositionList"


def _inner(direction, division, degree, duty="负责车身结构设计。", need="学历要求：硕士"):
    return {"researchDirection": direction, "division": division, "degree": degree,
            "jobDuty": duty, "jobRequirements": need, "workPlace": "深圳市"}


class BydCampusParseTest(unittest.TestCase):
    def _parse(self, row, detail=None, jd_url=_SCHOOL_URL):
        payload = {"jobs": [{"row": row, "detail": detail or {}, "jd_url": jd_url}]}
        return BydCampusAdapter().parse(json.dumps(payload, ensure_ascii=False))

    def test_graduate_position(self):
        detail = {"jobName": "高级车身集成工程师", "workPlace": "惠州市,深圳市", "positionInfoList": [
            _inner("车身技术开发", "汽车工程研究院", "00109"),
            _inner("车身技术开发", "商用车研究院", "00108,00107"),
            _inner("造型曲面", "商用车研究院", "00108", duty="完成外造型曲面的设计。"),
        ]}
        job = self._parse(_school_row("1", place="惠州市,深圳市"), detail)[0]
        self.assertEqual(job.company, "比亚迪")
        self.assertEqual(job.title, "高级车身集成工程师")
        self.assertEqual(job.location, "惠州市")                 # 官网列出的第一个城市
        self.assertEqual(job.job_type, "2027届校招")
        self.assertEqual(job.experience, "应届/不限")
        self.assertEqual(job.education, "本科")                  # 各方向里要求最低的那一档
        self.assertIsNone(job.posted_at)                          # 页面上那个日期叫「更新于」
        self.assertEqual(job.jd_url, _SCHOOL_URL)
        self.assertIn("//", job.jd_url.split("?", 1)[1])           # 密文里的双斜杠原样保留
        for piece in ("【岗位方向】车身技术开发、造型曲面", "【部门意向】汽车工程研究院、商用车研究院",
                      "【工作地点】惠州市、深圳市", "【学历】本科 / 硕士 / 博士",
                      "【车身技术开发｜汽车工程研究院、商用车研究院】", "【造型曲面｜商用车研究院】",
                      "完成外造型曲面的设计。"):
            self.assertIn(piece, job.summary)
        self.assertEqual(job.summary.count("负责车身结构设计。"), 1)   # 同一段正文只写一遍

    def test_intern_position_carries_no_grad_class(self):
        job = self._parse(_school_row("9", nature="008502"),
                          {"positionInfoList": [_inner("整车集成", "汽车工程研究院", "00107")]})[0]
        self.assertEqual(job.job_type, "实习")
        self.assertIsNone(job.experience)
        row = normalizer.normalize(job, source_id="s", company="比亚迪")
        self.assertIsNone(row["grad_class"])

    def test_list_only_row_still_emits_with_channel_type(self):
        job = self._parse(_school_row("1"))[0]                    # 快档：没有详情
        self.assertEqual((job.job_type, job.summary, job.education), ("2027届校招", None, None))

    def test_single_text_position_has_no_group_header(self):
        job = self._parse(_school_row("1"), {"positionInfoList": [_inner("整车集成", "汽车工程研究院", "00108")]})[0]
        self.assertNotIn("｜", job.summary)
        self.assertNotIn("【工作地点】", job.summary)             # 单城市不重复写

    def test_long_direction_list_is_capped(self):
        inner = [_inner(f"方向{i}", f"部门{i % 3}", "00107") for i in range(30)]
        job = self._parse(_school_row("1"), {"positionInfoList": inner})[0]
        self.assertIn("方向7 等 30 个方向", job.summary)
        self.assertNotIn("方向7、方向8", job.summary.split("【部门意向】")[0])

    def test_rows_that_must_not_be_written(self):
        self.assertEqual(self._parse(_school_row("1", nature="008504")), [])          # 不认识的招聘性质
        self.assertEqual(self._parse(_school_row("1", place="新加坡")), [])            # 没有在华城市
        self.assertEqual(self._parse(_school_row("1", name="")), [])
        social_url = "https://job.byd.com/portal/pc/#/social/socialPositionDetails?abc"
        self.assertEqual(self._parse(_school_row("1"), jd_url=social_url), [])        # 不是校招详情页

    def test_unknown_degree_codes_are_ignored(self):
        job = self._parse(_school_row("1"), {"positionInfoList": [_inner("a", "b", "00199,00108")]})[0]
        self.assertEqual(job.education, "硕士")
        job = self._parse(_school_row("1"), {"positionInfoList": [_inner("a", "b", "00199")]})[0]
        self.assertIsNone(job.education)

    def test_pipeline_classifies_by_channel(self):
        """走真实的 normalize + JS 分类器：应届生入口 → 校招 + 2027 届；实习生入口 → 实习。"""
        from recruitment_classify import classify
        grad = self._parse(_school_row("1"), {"positionInfoList": [_inner("整车集成", "汽车工程研究院", "00108")]})[0]
        intern = self._parse(_school_row("9", nature="008502"),
                             {"positionInfoList": [_inner("整车集成", "汽车工程研究院", "00107")]})[0]
        for job in (grad, intern):
            self.assertEqual(normalizer.validate_job_quality(job, _SCHOOL_LIST_URL), (True, ""))
        rows = [normalizer.normalize(j, source_id="s", company="比亚迪") for j in (grad, intern)]
        self.assertEqual(rows[0]["grad_class"], 2027)
        self.assertEqual([category for category, _explicit, _function in classify(rows)], ["校招", "实习"])

    def test_registered_in_run(self):
        import run
        self.assertIsInstance(run.ADAPTERS["byd_campus"], BydCampusAdapter)
        self.assertIn("byd_campus", run.DOMESTIC_ADAPTERS)
        self.assertNotIn("byd_campus", run._HTTPX_SAFE_ADAPTERS)   # 要起浏览器，只能走串行档


if __name__ == "__main__":
    unittest.main()
