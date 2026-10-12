"""tal adapter（好未来校招官网 job.tal.com）单测。不打真实网络。

钉死几件容易悄悄坏掉的事：
  ① offset 是页码不是偏移量、limit 最大 100 —— 收尾看「这一页有没有带来新岗位」；
  ② 集团站的列表包含两个品牌站的岗：集团源必须剔掉，品牌站取不全就整轮抛错；
  ③ 渠道号错了接口回「渠道不存在」：去入口脚本重读一次，读不到就抛错，绝不带空渠道号去问；
  ④ 占位岗「无职位投递」不是岗位；
  ⑤ 接口回 200 却不是一页正常数据时抛错，不许读成 0 个岗。
"""
import json
import unittest
from unittest.mock import patch

import run
from adapters import tal as tal_mod
from adapters.tal import TalAdapter, job_type_of, site_base

GROUP = "https://job.tal.com/campus/positions"
XES = "https://job.tal.com/campus/xes/positions"
ONLINE = "https://job.tal.com/campus/xesonline/positions"


def _row(job_id, title, locations=("北京市",), commitment="全职", tags=("应届毕业生", "校园招聘"),
         status="open", description="<p>岗位职责：负责课程教学与教研，跟进学生学习情况并持续改进教学方案。</p>"):
    return {"job_id": job_id, "mj_code": f"MJ{job_id}", "title": title, "status": status,
            "Locations": list(locations), "tag_names": list(tags), "department_name": "某事业部",
            "is_virtual": False, "hire_mode": "校招", "description": description, "commitment": commitment,
            "zhineng": {"id": 1, "name": "教师"}, "created_at": "2026-05-29 08:20:01",
            "updated_at": "2026-09-15 18:54:01", "publish_site": 0}


class _Resp:
    def __init__(self, payload=None, text="", status=200):
        self._p, self.text, self.status_code = payload, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tal_mod.httpx.HTTPStatusError("boom", request=None, response=None)

    def json(self):
        if self._p is None:
            raise ValueError("not json")
        return self._p


class _FakeClient:
    """按渠道号 + 页码出数据的假 client。channels = {渠道号: [整个站点的全部行]}。"""

    def __init__(self, channels, *, page_size=100, total_override=None, broken=None, pages=None):
        self.channels = channels
        self.page_size = page_size
        self.total_override = total_override or {}
        self.broken = broken or {}        # {(渠道号, 页码): payload 或 Exception}
        self.pages = pages or {}          # GET 的假页面 {url: 文本}
        self.posts = []
        self.gets = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, **kw):
        body = json or {}
        route, page = body.get("route_code"), body.get("offset")
        self.posts.append(dict(body))
        if (route, page) in self.broken:
            item = self.broken[(route, page)]
            if isinstance(item, Exception):
                raise item
            return _Resp(item)
        if route not in self.channels:
            return _Resp({"code": 400, "msg": "渠道不存在", "data": {}})
        rows = self.channels[route]
        size = min(body.get("limit") or self.page_size, self.page_size)   # 服务端最多给 100
        chunk = rows[page * size:(page + 1) * size]                       # offset 是页码
        return _Resp({"code": 200, "msg": "OK", "data": {
            "page": page, "page_size": size, "total": self.total_override.get(route, len(rows)), "list": chunk}})

    def get(self, url, **kw):
        self.gets.append(url)
        if url not in self.pages:
            return _Resp(text="", status=404)
        return _Resp(text=self.pages[url])


def _fetch(source_url, client):
    adapter = TalAdapter()
    with patch.object(tal_mod.httpx, "Client", lambda **kw: client):
        raw = adapter.fetch(source_url)
    return adapter, json.loads(raw)


class SiteBaseTest(unittest.TestCase):
    def test_three_sites(self):
        self.assertEqual(site_base(GROUP), "/campus")
        self.assertEqual(site_base(XES), "/campus/xes")
        self.assertEqual(site_base(ONLINE), "/campus/xesonline")
        self.assertEqual(site_base("https://job.tal.com/campus/xes/home"), "/campus/xes")

    def test_xesonline_is_not_swallowed_by_xes_prefix(self):
        # /campus/xesonline 也以 /campus/xes 开头：按字符串前缀比会把网校认成学而思
        self.assertEqual(site_base("https://job.tal.com/campus/xesonline"), "/campus/xesonline")

    def test_unknown_site_raises(self):
        for bad in ("https://example.com/campus/positions", "https://job.tal.com/social/home", "", None):
            with self.assertRaises(ValueError):
                site_base(bad)

    def test_unknown_path_under_campus_is_not_guessed_as_group_site(self):
        # 将来多出第四个站点（/campus/xxx）时不许安静地用集团渠道号去抓、写成另一条源的行
        for bad in ("https://job.tal.com/campus/xes2/positions", "https://job.tal.com/campus/newbrand/home",
                    "https://job.tal.com/campus/xes/positions/1f86d148-d017-4130-bdbb-9472480e61ae"):
            with self.assertRaises(ValueError, msg=bad):
                site_base(bad)


class PagingTest(unittest.TestCase):
    def test_offset_is_page_number_and_all_pages_collected(self):
        rows = [_row(f"id-{i}", f"岗位{i}") for i in range(139)]
        client = _FakeClient({"fXinVq": rows})
        adapter, payload = _fetch(XES, client)
        self.assertEqual(len(payload["rows"]), 139)
        self.assertEqual([p["offset"] for p in client.posts], [0, 1])       # 页码，不是 0 / 100
        self.assertTrue(all(p["limit"] == 100 and p["orgId"] == "tal" and p["site"] == "campus" for p in client.posts))
        self.assertEqual(adapter.reported_total, 139)
        self.assertTrue(adapter.fetch_complete)

    def test_repeated_page_does_not_count_as_complete(self):
        # 翻页参数没生效（每页都回同一批）：不能把重复行数成「抓全了」
        rows = [_row(f"id-{i}", f"岗位{i}") for i in range(100)]
        client = _FakeClient({"fXinVq": rows}, total_override={"fXinVq": 250})
        client.channels["fXinVq"] = rows + rows + rows
        adapter, payload = _fetch(XES, client)
        self.assertEqual(len(payload["rows"]), 100)
        self.assertEqual(adapter.reported_total, 250)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.coverage_stop_reason, "page_no_new_rows")

    def test_later_page_failure_keeps_rows_but_not_complete(self):
        rows = [_row(f"id-{i}", f"岗位{i}") for i in range(139)]
        client = _FakeClient({"fXinVq": rows}, broken={("fXinVq", 1): tal_mod.httpx.ConnectError("x")})
        adapter, payload = _fetch(XES, client)
        self.assertEqual(len(payload["rows"]), 100)
        self.assertFalse(adapter.fetch_complete)
        self.assertIsNone(adapter.coverage_stop_reason)

    def test_total_is_taken_from_the_first_page_only(self):
        # 第 2 页把总数报小了：不能让「抓全」的门槛跟着降
        rows = [_row(f"id-{i}", f"岗位{i}") for i in range(100)]
        shrunk = {"code": 200, "msg": "OK", "data": {"page": 1, "page_size": 100, "total": 100, "list": []}}
        client = _FakeClient({"fXinVq": rows}, total_override={"fXinVq": 139}, broken={("fXinVq", 1): shrunk})
        adapter, payload = _fetch(XES, client)
        self.assertEqual(len(payload["rows"]), 100)
        self.assertEqual(adapter.reported_total, 139)
        self.assertFalse(adapter.fetch_complete)

    def test_list_that_is_not_a_list_raises(self):
        bad = {"code": 200, "msg": "OK", "data": {"total": 3, "list": {"0": "x"}}}
        with self.assertRaises(RuntimeError):
            _fetch(XES, _FakeClient({"fXinVq": []}, broken={("fXinVq", 0): bad}))

    def test_status_field_changing_shape_is_an_error_not_zero_jobs(self):
        # 行都在、标题都在，只是 status 不再叫 open：一条都留不下时必须报错，不许记成「0 个岗、成功」
        rows = [_row(f"id-{i}", f"岗位{i}", status="published") for i in range(5)]
        with self.assertRaises(RuntimeError) as ctx:
            _fetch(XES, _FakeClient({"fXinVq": rows}))
        self.assertIn("status", str(ctx.exception))

    def test_rows_without_titles_only_is_an_error(self):
        rows = [dict(_row(f"id-{i}", "x"), title="") for i in range(3)]
        with self.assertRaises(RuntimeError):
            _fetch(XES, _FakeClient({"fXinVq": rows}))

    def test_first_page_failure_raises(self):
        client = _FakeClient({"fXinVq": []}, broken={("fXinVq", 0): tal_mod.httpx.ConnectError("x")})
        with self.assertRaises(RuntimeError):
            _fetch(XES, client)

    def test_http_200_without_list_raises(self):
        client = _FakeClient({"fXinVq": []}, broken={("fXinVq", 0): {"code": 200, "msg": "OK", "data": {}}})
        with self.assertRaises(RuntimeError):
            _fetch(XES, client)

    def test_brand_site_may_be_empty(self):
        # 品牌站一批招完、下一批没开是正常的：0 岗、抓全
        adapter, payload = _fetch(ONLINE, _FakeClient({"iyZkOo": []}))
        self.assertEqual(payload["rows"], [])
        self.assertEqual(adapter.reported_total, 0)
        self.assertTrue(adapter.fetch_complete)


class GroupSiteTest(unittest.TestCase):
    def _channels(self):
        xes = [_row(f"x-{i}", f"学而思岗{i}") for i in range(3)]
        online = [_row(f"o-{i}", f"网校岗{i}") for i in range(2)]
        own = [_row(f"g-{i}", f"集团岗{i}") for i in range(4)]
        placeholder = _row("p-0", "无职位投递", description="<p>无职位投递入口</p>")
        return {"kg8Meh": own[:2] + xes + [placeholder] + online + own[2:], "fXinVq": xes, "iyZkOo": online}

    def test_group_source_drops_brand_site_jobs_and_placeholder(self):
        adapter, payload = _fetch(GROUP, _FakeClient(self._channels()))
        ids = [r["job_id"] for r in payload["rows"]]
        self.assertEqual(ids, ["g-0", "g-1", "g-2", "g-3"])
        self.assertEqual(adapter.reported_total, 4)     # 10 个里该这条源写的只有 4 个
        self.assertTrue(adapter.fetch_complete)

    def test_brand_source_keeps_its_own_jobs(self):
        adapter, payload = _fetch(XES, _FakeClient(self._channels()))
        self.assertEqual([r["job_id"] for r in payload["rows"]], ["x-0", "x-1", "x-2"])

    def test_group_source_raises_when_brand_site_incomplete(self):
        # 品牌站自报 9 个只取到 3 个：没法确定哪些岗该剔，本轮不写
        client = _FakeClient(self._channels(), total_override={"fXinVq": 9})
        with self.assertRaises(RuntimeError) as ctx:
            _fetch(GROUP, client)
        self.assertIn("/campus/xes", str(ctx.exception))

    def test_group_source_raises_when_brand_site_unreachable(self):
        client = _FakeClient(self._channels(), broken={("iyZkOo", 0): tal_mod.httpx.ConnectError("x")})
        with self.assertRaises(RuntimeError):
            _fetch(GROUP, client)

    def test_group_site_empty_is_an_error_not_zero_jobs(self):
        with self.assertRaises(RuntimeError):
            _fetch(GROUP, _FakeClient({"kg8Meh": [], "fXinVq": [], "iyZkOo": []}))

    def test_non_open_rows_are_dropped(self):
        ch = {"fXinVq": [_row("a", "在招岗"), _row("b", "暂停岗", status="pause")]}
        adapter, payload = _fetch(XES, _FakeClient(ch))
        self.assertEqual([r["job_id"] for r in payload["rows"]], ["a"])
        self.assertEqual(adapter.reported_total, 1)


class RouteCodeTest(unittest.TestCase):
    HOME = "https://job.tal.com/campus/xes/home"
    SCRIPT = "https://cdn.example.com/app/prod/js/index-AbC123.js"

    def _pages(self, code):
        return {self.HOME: f'<script type="module" crossorigin src="{self.SCRIPT}"></script>',
                self.SCRIPT: f'x={{VITE_JOB_ORG:"tal",VITE_JOB_DEFAULT_CHANNEL:"{code}"}}'}

    def test_changed_route_code_is_reread_from_entry_script(self):
        rows = [_row("a", "岗位A")]
        client = _FakeClient({"NewCode1": rows}, pages=self._pages("NewCode1"))
        adapter, payload = _fetch(XES, client)
        self.assertEqual([r["job_id"] for r in payload["rows"]], ["a"])
        self.assertEqual([p["route_code"] for p in client.posts], ["fXinVq", "NewCode1"])

    def test_route_code_not_found_raises(self):
        client = _FakeClient({}, pages={})      # 入口页都读不到
        with self.assertRaises(RuntimeError) as ctx:
            _fetch(XES, client)
        self.assertIn("渠道不存在", str(ctx.exception))

    def test_same_code_in_script_raises_instead_of_looping(self):
        client = _FakeClient({}, pages=self._pages("fXinVq"))
        with self.assertRaises(RuntimeError):
            _fetch(XES, client)
        self.assertEqual(len(client.posts), 1)

    def test_route_code_of_another_site_is_not_adopted(self):
        # 入口脚本里读回来的是集团站的渠道号：拿错了页面，用它会把集团的岗写到学而思名下
        rows = [_row("g", "集团岗")]
        client = _FakeClient({"kg8Meh": rows}, pages=self._pages("kg8Meh"))
        tal_mod_channels = dict(tal_mod._CHANNELS)
        with patch.dict(tal_mod._CHANNELS, {**tal_mod_channels, "/campus/xes": "Stale000"}, clear=True):
            with self.assertRaises(RuntimeError):
                _fetch(XES, client)
        self.assertEqual([p["route_code"] for p in client.posts], ["Stale000"])

    def test_empty_route_code_is_never_sent(self):
        # 空渠道号会取回整个租户的岗（含没对外发布的）
        adapter = TalAdapter()
        client = _FakeClient({})
        with self.assertRaises(RuntimeError):
            adapter._list_page(client, "", 0)
        self.assertEqual(client.posts, [])


class ParseTest(unittest.TestCase):
    def _parse(self, base, rows):
        return TalAdapter().parse(json.dumps({"base": base, "rows": rows}, ensure_ascii=False))

    def test_jd_url_uses_the_site_own_detail_route(self):
        jobs = self._parse("/campus/xes", [_row("1f86d148-d017-4130-bdbb-9472480e61ae", "科学思维教师-27校招")])
        self.assertEqual(jobs[0].jd_url,
                         "https://job.tal.com/campus/xes/positions/1f86d148-d017-4130-bdbb-9472480e61ae")
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)
        jobs = self._parse("/campus", [_row("abc", "27校招-数学教研")])
        self.assertEqual(jobs[0].jd_url, "https://job.tal.com/campus/positions/abc")

    def test_company_is_left_to_the_source_row(self):
        self.assertEqual(self._parse("/campus", [_row("a", "岗位A")])[0].company, "")

    def test_multi_city_locations_are_all_handed_over(self):
        job = self._parse("/campus/xes", [_row("a", "科学思维教师-27校招", locations=("北京市", "上海市", "杭州市"))])[0]
        for city in ("北京", "上海", "杭州"):
            self.assertIn(city, job.location)

    def test_empty_locations_give_none(self):
        self.assertIsNone(self._parse("/campus", [_row("a", "HRBP专员", locations=())])[0].location)

    def test_summary_carries_function_and_description_and_no_publish_date(self):
        job = self._parse("/campus", [_row("a", "岗位A")])[0]
        self.assertIn("职能类型：教师", job.summary)
        self.assertIn("岗位职责", job.summary)
        self.assertIsNone(job.posted_at)        # 页面上只有「更新于」，不当发布日

    def test_unknown_base_or_broken_payload_gives_nothing(self):
        self.assertEqual(self._parse("/social", [_row("a", "岗位A")]), [])
        self.assertEqual(TalAdapter().parse("not json"), [])

    def test_rows_without_id_or_title_are_skipped(self):
        rows = [_row("", "没有岗位号"), _row("a", ""), _row("b", "正常岗")]
        self.assertEqual([j.title for j in self._parse("/campus", rows)], ["正常岗"])


class JobTypeTest(unittest.TestCase):
    def test_intern_project_tags_mean_intern(self):
        self.assertEqual(job_type_of(_row("a", "产品实习生", commitment="实习", tags=("实习生", "日常实习"))), "实习")

    def test_conversion_roles_are_reported_as_campus(self):
        # 「27实习转正-…」工作性质写实习 / 兼职，对方的项目标签是「校园招聘-实习转正」
        for commitment in ("实习", "兼职", "全职"):
            row = _row("a", "27实习转正-AI研发", commitment=commitment, tags=("应届毕业生", "校园招聘-实习转正"))
            self.assertEqual(job_type_of(row), "校园招聘", commitment)
        self.assertEqual(job_type_of(_row("a", "27实习转正-算法工程师", commitment="兼职", tags=())), "校园招聘")

    def test_intern_commitment_without_tags_is_intern(self):
        self.assertEqual(job_type_of(_row("a", "英文动画视频助理", commitment="实习", tags=())), "实习")

    def test_default_is_campus(self):
        self.assertEqual(job_type_of(_row("a", "科学思维教师-27校招")), "校园招聘")
        self.assertEqual(job_type_of({"title": "只有标题"}), "校园招聘")


class RegistrationTest(unittest.TestCase):
    def test_registered_as_domestic_httpx_adapter(self):
        self.assertIsInstance(run.ADAPTERS["tal"], TalAdapter)
        self.assertIn("tal", run.DOMESTIC_ADAPTERS)
        self.assertIn("tal", run._HTTPX_SAFE_ADAPTERS)      # 纯 httpx，不该排进浏览器车道

    def test_absence_liveness_is_declared(self):
        # 列表是该站对外的全集（自报总数 = 翻到的条数），抓全的那一轮才按缺席判撤岗
        self.assertTrue(TalAdapter.supports_absence_liveness)


if __name__ == "__main__":
    unittest.main()
