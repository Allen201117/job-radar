"""huawei_campus adapter 单测。

这个 adapter 存在的理由本身就是一条教训：老门户 reccampportal 传 jobType=2 返 totalRows=0，
据此判「华为没开校招」是**错的**——华为 2027 届秋招 2026-08-15 就启动了，只是搬到了新站新网关。
所以这里除了常规映射，重点钉死三件容易悄悄坏掉的事：
  ① 详情链用 advertisementId（同行还有两个长得很像的 id，取错就是坏链）；
  ② 拿不到「岗位意向」正文时**不许**用占位句「请您详见岗位意向中的岗位职责」凑正文；
  ③ 地点必须来自列表自带的 jobAddress —— 中文 jobCity 只在详情接口里有，
     快档（CRAWL_DETAIL_CAP=0）拿不到，靠它取地点会让整源无地点。
"""
import json
import os
import unittest
from unittest.mock import patch

from adapters import huawei_campus as hw_mod
from adapters.huawei_campus import HuaweiCampusAdapter


def _job_page(total, rows):
    return {"status": "SUCCESS", "data": {"pageVO": {"totalRows": total}, "result": rows}}


def _row(adv, job_id, name, address="China\\Guangdong-Shenzhen,China\\Beijing-Beijing"):
    return {
        "advertisementId": adv,
        "advertisementsIntegrationId": adv + 100000,   # 故意与 advertisementId 不同
        "jobId": job_id,
        "jobName": name,
        "jobAddress": address,
        "deptName": "ICT BG",
        "mainBusiness": "请您详见岗位意向中的岗位职责",
        "jobRequire": "请您详见岗位意向中的岗位要求",
        "scenarioName": "应届生",
        "lastUpdateDate": "2026-08-17",
    }


class _FakeClient:
    """按 URL 路由的假 client：getJobPage 返分页，getPositionIntentionList 返方向正文。"""

    def __init__(self, pages_by_scenario, intentions=None):
        self.pages = pages_by_scenario
        self.intentions = intentions if intentions is not None else {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, **kw):
        body = json or {}
        self.calls.append((url, body))
        if "getJobPage" in url:
            scenario = (body.get("recruitmentType") or ["?"])[0]
            queue = self.pages.get(scenario) or []
            page = body.get("curPage", 1)
            payload = queue[page - 1] if page - 1 < len(queue) else _job_page(None, [])
            return _Resp(payload)
        if "getPositionIntentionList" in url:
            return _Resp({"status": "SUCCESS", "data": self.intentions.get(body.get("jobId"), [])})
        raise AssertionError(f"unexpected POST {url}")


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class HuaweiCampusTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    tearDown = setUp

    def _run(self, client):
        adapter = HuaweiCampusAdapter()
        adapter.regions = ["CN"]
        with patch.object(hw_mod.httpx, "Client", lambda **kw: client):
            raw = adapter.fetch("https://career.huawei.com/cn/campus-recruitment")
        return adapter, adapter.parse(raw)

    def test_detail_url_uses_advertisement_id(self):
        """同一行里 advertisementsIntegrationId / jobId 都存在且值不同，取错就是坏链。"""
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(1, [_row(36384, 103891, "AI Infra工程师")])],
                              "INTERN": [_job_page(0, [])]})
        _, jobs = self._run(client)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url,
                         "https://career.huawei.com/cn/job-details?advertisementId=36384")
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)

    def test_location_comes_from_list_job_address_not_detail(self):
        """快档不富化时也必须有地点——jobAddress 在列表里就有，中文 jobCity 只在详情接口。"""
        os.environ["CRAWL_DETAIL_CAP"] = "0"
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(1, [_row(1, 2, "岗A")])],
                              "INTERN": [_job_page(0, [])]})
        _, jobs = self._run(client)
        self.assertEqual(jobs[0].location, "China\\Guangdong-Shenzhen")

    def test_placeholder_text_never_becomes_summary(self):
        """没拿到方向正文时不许拿占位句凑数——那会把薄卡凑够 60 字混进「有效在招」。"""
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(1, [_row(1, 2, "岗A")])],
                              "INTERN": [_job_page(0, [])]}, intentions={})
        _, jobs = self._run(client)
        self.assertNotIn("请您详见", jobs[0].summary or "")

    def test_intention_text_becomes_summary(self):
        client = _FakeClient(
            {"FRESH_GRADUATE": [_job_page(1, [_row(1, 2, "岗A")])], "INTERN": [_job_page(0, [])]},
            intentions={2: [{"positionIntention": "AI算子技术",
                             "jobResponsibilities": "参与算子设计<br>推动落地",
                             "jobDemand": "计算机相关专业<br>熟悉大模型",
                             "jobPlaceName": "北京/深圳"}]})
        _, jobs = self._run(client)
        summary = jobs[0].summary or ""
        self.assertIn("AI算子技术", summary)
        self.assertIn("参与算子设计\n推动落地", summary, "<br> 必须转成真换行")
        self.assertIn("工作地点：北京/深圳", summary, "中文城市串拿到了就该展示")

    def test_complete_requires_both_scenarios_drained(self):
        """两个场景各自抓到自报总数才算抓全——单看去重后条数会因跨场景重复而永远为 False。"""
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(1, [_row(1, 2, "岗A")])],
                              "INTERN": [_job_page(1, [_row(3, 4, "岗B")])]})
        adapter, jobs = self._run(client)
        self.assertEqual(adapter.reported_total, 2)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(len(jobs), 2)

    def test_short_channel_marks_incomplete(self):
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(99, [_row(1, 2, "岗A")]), _job_page(99, [])],
                              "INTERN": [_job_page(0, [])]})
        adapter, _ = self._run(client)
        self.assertFalse(adapter.fetch_complete)

    def test_empty_gateway_raises_instead_of_pretending_no_campus(self):
        """网关返 200 但 data 空（多半是 x-* 头缺失）必须抛错记 failed，
        绝不能安静地返 0 条 —— 那正是「华为没开校招」这个错误结论的来源。"""
        client = _FakeClient({"FRESH_GRADUATE": [{"status": "SUCCESS", "data": {}}],
                              "INTERN": [{"status": "SUCCESS", "data": {}}]})
        adapter = HuaweiCampusAdapter()
        adapter.regions = ["CN"]
        with patch.object(hw_mod.httpx, "Client", lambda **kw: client):
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://career.huawei.com/cn/campus-recruitment")

    def test_required_gateway_headers_present(self):
        """缺任何一个 x-* 头，网关返 200 但 data 为空 —— 头列表本身就是契约。"""
        headers = HuaweiCampusAdapter()._headers()
        for key in ("x-hw-id", "x-jalor-tenantalias", "x-language", "x-alb-gray", "x-referer"):
            self.assertIn(key, headers, f"缺少必需请求头 {key}")

    def test_dedup_across_scenarios_by_advertisement_id(self):
        client = _FakeClient({"FRESH_GRADUATE": [_job_page(1, [_row(1, 2, "岗A")])],
                              "INTERN": [_job_page(1, [_row(1, 2, "岗A")])]})
        _, jobs = self._run(client)
        self.assertEqual(len(jobs), 1, "同一个 advertisementId 跨场景只入一条")


if __name__ == "__main__":
    unittest.main()
