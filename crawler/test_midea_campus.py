"""美的校招 adapter + 逐岗探活器单测（离线夹具，不打真实网络）。

三组重点：
  ① parse：jd_url 取 positionId（不是 projectPositionId）、地区门按 sources.regions 走、
     届别只从项目名里来（**绝不能从 numberOfSessions 猜**）；
  ② 翻页：末页判据是「这一页有没有带来新 positionId」——这个接口的 pageSize 被服务端顶到 20、
     `pageNum` 会被静默忽略，用「本页条数 < pageSize」判末页会无限翻同一页；
     完整性**逐项目判**，不拿各项目 total 之和当分母；
  ③ 判死：双条件，含糊信号一律不判死。
"""
import json
import os
import unittest
from unittest import mock

import enrich
from adapters import midea_campus as mod
from adapters.midea_campus import MideaCampusAdapter
from grad_class import extract_grad_class
from normalizer import clean_summary

_CAMPUS_PROJECT = {
    "projectRuleId": "055bb05d-1957-4ea0-bb21-873ca0164d84",
    "projectRuleName": "2027届美的星校园招聘",
    "employementCategory": 1,
    "projectType": "1",
    "numberOfSessions": "2027",
    "status": 1,
}
_DAILY_INTERN_PROJECT = {
    "projectRuleId": "4286dfd5-d9e8-4146-8f8c-98093833a81b",
    "projectRuleName": "日常实习生招聘通道",
    "employementCategory": 4,
    "projectType": "9",
    # ⚠️ 项目名里没有届别，但对方在这里写着 2026 —— 实测毕业时间窗是 2026-01-01~2028-12-31，
    # 把它当届别就是把一批 26/27/28 届通吃的实习岗全标成 2026 届。
    "numberOfSessions": "2026",
    "status": 1,
}
_COOP_INTERN_PROJECT = dict(_DAILY_INTERN_PROJECT,
                            projectRuleId="ecfa0634-f99f-415e-88c4-aa081483594b",
                            projectRuleName="校企合作实习招聘通道", projectType="7")


def _row(pid, project=None, **over):
    project = project or _CAMPUS_PROJECT
    row = {
        "positionId": pid,
        "projectRuleId": project["projectRuleId"],
        "projectType": project["projectType"],
        "employementCategory": project["employementCategory"],
        "projectPositionId": "f94d8552fd044af6bb86064f53ee7e0b",
        "projectPositionName": "研究员-焊接工艺",
        "recruitCategoryName": "研发技术类",
        "workPlaceCode": "上海市,佛山市",
        "workplaceDtoList": [{"workPlaceName": "上海市"}, {"workPlaceName": "佛山市"}],
        "orgUnitList": [{"localUnitName": "新能源事业部"}],
        "projectPositionDto": {
            "projectPositionId": "f94d8552fd044af6bb86064f53ee7e0b",
            "positionName": "研究员-焊接工艺",
            "largeTypeName": "研发技术类",
            "jobResponsibility": "1、负责焊接用新材料、新技术、新设备的工艺研发。",
            "jobRequirement": "1、硕士研究生学历，焊接、材料、机械等相关专业。",
        },
        "_project": project,
    }
    row.update(over)
    return row


def _parse(rows):
    return MideaCampusAdapter().parse(json.dumps({"rows": rows}, ensure_ascii=False))


class MideaCampusParseTest(unittest.TestCase):
    def test_parse_uses_position_id_not_project_position_id(self):
        jobs = _parse([_row("8b8b36a5a07bc25301a08e4679cd4aba")])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "美的集团")
        self.assertEqual(job.title, "研究员-焊接工艺")
        self.assertEqual(job.location, "上海市")
        self.assertEqual(job.job_type, "校园招聘")
        self.assertEqual(
            job.jd_url,
            "https://careers.midea.com/schoolOut/post/details"
            "?positionId=8b8b36a5a07bc25301a08e4679cd4aba")
        # projectPositionId 是岗位模板 id，拿它拼链接会开不出详情
        self.assertNotIn("f94d8552fd044af6bb86064f53ee7e0b", job.jd_url)
        self.assertEqual(job.apply_url, job.jd_url)
        self.assertIn("工作城市：上海市、佛山市", job.summary)
        self.assertIn("用人单位：新能源事业部", job.summary)
        self.assertIn("负责焊接用新材料", job.summary)

    def test_grad_class_comes_from_project_name(self):
        jobs = _parse([_row("a" * 32)])
        self.assertEqual(
            extract_grad_class(jobs[0].title, jobs[0].job_type, clean_summary(jobs[0].summary)),
            2027)

    def test_intern_channel_leaves_grad_class_blank(self):
        """🚩 日常实习通道的 numberOfSessions=2026，但它面向 26/27/28 届。
        写进 summary 就会把这批岗全标成 2026 届 —— 留白才是对的。"""
        jobs = _parse([_row("b" * 32, project=_DAILY_INTERN_PROJECT)])
        self.assertIn("招聘项目：日常实习生招聘通道", jobs[0].summary)
        self.assertNotIn("2026", jobs[0].summary)
        self.assertIsNone(
            extract_grad_class(jobs[0].title, jobs[0].job_type, clean_summary(jobs[0].summary)))

    def test_employement_category_maps_to_job_type(self):
        self.assertEqual(_parse([_row("c" * 32, project=_DAILY_INTERN_PROJECT)])[0].job_type,
                         "日常实习")
        self.assertEqual(_parse([_row("d" * 32, project=_COOP_INTERN_PROJECT)])[0].job_type,
                         "实习")
        self.assertEqual(_parse([_row("e" * 32)])[0].job_type, "校园招聘")

    def test_overseas_location_is_dropped_by_region_gate(self):
        self.assertEqual(_parse([_row("f" * 32, workPlaceCode="Singapore")]), [])

    def test_taiwan_is_dropped_even_under_the_relaxed_gate(self):
        self.assertEqual(_parse([_row("f" * 32, workPlaceCode="台北市")]), [])

    def test_county_level_city_is_kept_not_dropped(self):
        """昆山市是江苏的县级市，词表按设计只收到地级市 → 严格判据会丢掉这个真·在招岗
        （2026-09-18 live 535 行里正好 1 行）。证据不足 ≠ 证据相反。"""
        jobs = _parse([_row("f" * 32, workPlaceCode="昆山市")])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "昆山市")

    def test_rows_without_id_or_title_are_skipped(self):
        self.assertEqual(
            _parse([_row("", ), _row("g" * 32, projectPositionName="",
                                     projectPositionDto={"positionName": " "})]),
            [])

    def test_malformed_payload_returns_empty(self):
        self.assertEqual(MideaCampusAdapter().parse("nope"), [])


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """按 (projectRuleId, pageIndex) 返回预置页；同时记录请求体好断言翻页参数。"""

    def __init__(self, projects, pages, ignore_page_index=False):
        self.projects = projects
        self.pages = pages          # {(prid, page): [row,...]}
        self.totals = {}
        self.ignore_page_index = ignore_page_index
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def get(self, url, params=None):
        self.calls.append(("GET", url, params))
        return _Resp({"code": "0", "data": self.projects})

    def post(self, url, json=None):
        body = json or {}
        self.calls.append(("POST", url, body))
        prid = body.get("projectRuleId")
        page = 1 if self.ignore_page_index else body.get("pageIndex")
        rows = self.pages.get((prid, page), [])
        total = self.totals.get(prid)
        return _Resp({"code": "0", "data": {
            "total": total,
            "info": {"pageIndex": page, "pageSize": 20,
                     "totalPage": max(1, -(-(total or 0) // 20))},
            "data": rows,
        }})


def _run(projects, pages, totals, ignore_page_index=False):
    client = _FakeClient(projects, pages, ignore_page_index)
    client.totals = totals
    with mock.patch.object(mod.httpx, "Client", lambda *a, **k: client):
        adapter = MideaCampusAdapter()
        raw = adapter.fetch("https://careers.midea.com/schoolOut/post")
    return adapter, __import__("json").loads(raw)["rows"], client


class MideaCampusFetchTest(unittest.TestCase):
    def test_paginates_with_page_index_and_reports_complete(self):
        prid = _CAMPUS_PROJECT["projectRuleId"]
        pages = {
            (prid, 1): [_row(f"{i:032x}") for i in range(20)],
            (prid, 2): [_row(f"{i:032x}") for i in range(20, 23)],
        }
        adapter, rows, client = _run([_CAMPUS_PROJECT], pages, {prid: 23})
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 23)
        self.assertEqual(len(rows), 23)
        posts = [c for c in client.calls if c[0] == "POST"]
        # 翻页参数必须是 pageIndex —— pageNum 会被服务端静默忽略（2026-09-18 live 实证）
        self.assertEqual([c[2]["pageIndex"] for c in posts], [1, 2])
        self.assertTrue(all("pageNum" not in c[2] for c in posts))

    def test_ignored_pagination_param_is_caught_not_looped_forever(self):
        """模拟「翻页参数被忽略、每页回同一批」：必须在第 2 页就停，且如实记没抓全。
        若末页判据用「本页条数 < pageSize」，这里会一直翻到 MAX_PAGES 还自称抓全。"""
        prid = _CAMPUS_PROJECT["projectRuleId"]
        page1 = [_row(f"{i:032x}") for i in range(20)]
        adapter, rows, client = _run([_CAMPUS_PROJECT], {(prid, 1): page1}, {prid: 152},
                                     ignore_page_index=True)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(len(rows), 20)
        self.assertEqual(len([c for c in client.calls if c[0] == "POST"]), 2)

    def test_completeness_is_judged_per_project_not_by_sum(self):
        """一个项目没抓全 → 整源不算抓全，哪怕另一个项目超额。
        （不拿「去重后条数 >= 各项目 total 之和」判，渠道重叠会让它恒为假。）"""
        a, b = _CAMPUS_PROJECT, _COOP_INTERN_PROJECT
        pages = {
            (a["projectRuleId"], 1): [_row(f"{i:032x}", project=a) for i in range(3)],
            (b["projectRuleId"], 1): [_row(f"{i + 100:032x}", project=b) for i in range(2)],
        }
        adapter, rows, _ = _run([a, b], pages,
                                {a["projectRuleId"]: 3, b["projectRuleId"]: 9})
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(len(rows), 5)

    def test_all_projects_drained_is_complete(self):
        a, b = _CAMPUS_PROJECT, _COOP_INTERN_PROJECT
        pages = {
            (a["projectRuleId"], 1): [_row(f"{i:032x}", project=a) for i in range(3)],
            (b["projectRuleId"], 1): [_row(f"{i + 100:032x}", project=b) for i in range(2)],
        }
        adapter, rows, _ = _run([a, b], pages,
                                {a["projectRuleId"]: 3, b["projectRuleId"]: 2})
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 5)
        self.assertEqual(len(rows), 5)

    def test_no_running_project_is_a_legitimate_zero(self):
        adapter, rows, _ = _run([], {}, {})
        self.assertEqual(rows, [])
        self.assertEqual(adapter.reported_total, 0)
        self.assertTrue(adapter.fetch_complete)

    def test_hitting_the_list_cap_is_never_reported_as_complete(self):
        """同 base.resolve_list_cap 立的规矩：撞单源条数上限必须 fetch_complete=False。"""
        prid = _CAMPUS_PROJECT["projectRuleId"]
        pages = {(prid, n): [_row(f"{i:032x}") for i in range((n - 1) * 20, n * 20)]
                 for n in range(1, 9)}
        with mock.patch.dict(os.environ, {"CRAWL_MAX_JOBS": "20"}):
            adapter, rows, _ = _run([_CAMPUS_PROJECT], pages, {prid: 152})
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(len(rows), 20)

    def test_list_cap_is_shared_across_projects_not_per_project(self):
        """`resolve_list_cap` 的语义是**单源**上限。预算若逐项目各给一份，
        4 个项目就会变成「上限 × 4」，单源上限这个旋钮等于失效。"""
        a, b = _CAMPUS_PROJECT, _COOP_INTERN_PROJECT
        pages = {
            (a["projectRuleId"], 1): [_row(f"{i:032x}", project=a) for i in range(20)],
            (a["projectRuleId"], 2): [_row(f"{i + 20:032x}", project=a) for i in range(20)],
            (b["projectRuleId"], 1): [_row(f"{i + 100:032x}", project=b) for i in range(20)],
        }
        with mock.patch.dict(os.environ, {"CRAWL_MAX_JOBS": "20"}):
            adapter, rows, client = _run([a, b], pages,
                                         {a["projectRuleId"]: 152, b["projectRuleId"]: 169})
        # 第一个项目就把 20 条预算吃光 → 第二个项目一个请求都不该发
        self.assertEqual(len(rows), 20)
        self.assertFalse(adapter.fetch_complete)
        posted_prids = {c[2].get("projectRuleId") for c in client.calls if c[0] == "POST"}
        self.assertEqual(posted_prids, {a["projectRuleId"]})

    def test_page_cap_follows_crawl_max_jobs_not_a_hardcoded_number(self):
        """页数上限必须跟着 CRAWL_MAX_JOBS 走（resolve_page_cap），不能写死。
        CRAWL_MAX_JOBS=60 → ceil(60/20)=3 页就停。"""
        prid = _CAMPUS_PROJECT["projectRuleId"]
        pages = {(prid, n): [_row(f"{i:032x}") for i in range((n - 1) * 20, n * 20)]
                 for n in range(1, 20)}
        with mock.patch.dict(os.environ, {"CRAWL_MAX_JOBS": "60"}):
            adapter, rows, client = _run([_CAMPUS_PROJECT], pages, {prid: 999})
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(len([c for c in client.calls if c[0] == "POST"]), 3)
        self.assertEqual(len(rows), 60)

    def test_project_list_broken_shape_raises(self):
        client = _FakeClient({"oops": 1}, {})
        with mock.patch.object(mod.httpx, "Client", lambda *a, **k: client):
            with self.assertRaises(RuntimeError):
                MideaCampusAdapter().fetch("https://careers.midea.com/schoolOut/post")


class _LiveResp:
    def __init__(self, payload=None, status=200, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class MideaCampusLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": ("https://careers.midea.com/schoolOut/post/details"
                       "?positionId=8b8b352da090c1b601a0acd2f4c1181a")}

    @staticmethod
    def _patch(resp):
        return mock.patch.object(enrich.httpx, "post", lambda *a, **k: resp)

    def test_live_publish_status_1_is_not_closed(self):
        with self._patch(_LiveResp({"code": "0", "data": {
                "projectPositionName": "C++开发工程师", "publishStatus": 1}})):
            self.assertEqual(enrich._detail_midea_campus(self._ROW, {}), "")

    def test_data_null_raises_job_closed(self):
        # 不存在的 positionId：code 照样是 "0"，区别只在 data 是 null
        with self._patch(_LiveResp({"code": "0", "message": None, "data": None})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_publish_status_2_raises_job_closed(self):
        with self._patch(_LiveResp({"code": "0", "data": {
                "projectPositionName": "电控硬件开发助理工程师-小家电", "publishStatus": 2}})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_non_zero_code_is_unknown_not_closed(self):
        """网关/业务错误码不是撤岗 —— 按 code!=0 判死会一轮清空整个源。"""
        with self._patch(_LiveResp({"code": "500", "message": "系统异常", "data": None})):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_missing_data_key_is_unknown_not_closed(self):
        with self._patch(_LiveResp({"code": "0", "message": None})):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_record_without_name_is_unknown_not_closed(self):
        """空 positionId 实测会返回一个 14 键全空的壳 —— 半截响应不判死。"""
        with self._patch(_LiveResp({"code": "0", "data": {"publishStatus": None}})):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_unknown_publish_status_is_not_closed(self):
        """只认实测过的 2；冒出第三种取值时宁可漏判也不错杀。"""
        with self._patch(_LiveResp({"code": "0", "data": {
                "projectPositionName": "研究员", "publishStatus": 9}})):
            self.assertEqual(enrich._detail_midea_campus(self._ROW, {}), "")

    def test_transient_5xx_is_unknown(self):
        with self._patch(_LiveResp({"code": "0", "data": None}, status=503)):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_non_json_is_unknown(self):
        with self._patch(_LiveResp(None, text="<html>waf</html>")):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_midea_campus(self._ROW, {})

    def test_jd_url_without_position_id_makes_no_request(self):
        def _post(*a, **k):
            raise AssertionError("不该发请求")

        with mock.patch.object(enrich.httpx, "post", _post):
            self.assertEqual(
                enrich._detail_midea_campus(
                    {"jd_url": "https://careers.midea.com/schoolOut/post"}, {}), "")


if __name__ == "__main__":
    unittest.main()
