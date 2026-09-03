"""netease_campus 单测（纯函数 + mock httpx，不打真网络）。

红线：网易后台保留 2019 年至今的全部招聘项目，对早已结束的项目照样返回岗位，
`projectStatus` 恒为 1 毫无区分度。**项目筛选错了就是把七年前的死岗当在招入库**，
所以 project_is_current 的每条分支都要钉死。
"""
import json
import unittest
from unittest import mock

from adapters import netease_campus
from adapters.netease_campus import NeteaseCampusAdapter, cohort_year, project_is_current


class ProjectIsCurrentTest(unittest.TestCase):
    def test_future_cohort_is_kept(self):
        self.assertTrue(project_is_current("2027届雷火秋季校园招聘", False, 2027))
        self.assertTrue(project_is_current("网易互娱2028届实习生项目", False, 2027))

    def test_past_cohort_is_dropped_even_though_api_still_returns_jobs(self):
        """live 实测这几个项目仍能返回岗位，全靠这条规则挡住。"""
        for name in ("2026届互联网校招-秋招", "2025届互联网秋季校园招聘",
                     "2019届网易互联网秋招", "2026届雷火校招补招"):
            self.assertFalse(project_is_current(name, False, 2027), name)

    def test_test_projects_are_dropped_even_if_in_navigation(self):
        """后台真有 4 个测试项目，其中一个还挂着 3 个岗。"""
        self.assertFalse(project_is_current("测试test-互娱测试项目", True, 2027))
        self.assertFalse(project_is_current("测试test-雷火配合EHR调试新接口项目（勿动）", True, 2027))

    def test_no_cohort_in_name_relies_on_navigation(self):
        """《蛋仔派对》AI实习专项 这类没有届次的，只信站点自己的导航，不猜。"""
        self.assertTrue(project_is_current("《蛋仔派对》AI实习专项", True, 2027))
        self.assertFalse(project_is_current("《蛋仔派对》AI实习专项", False, 2027))
        self.assertFalse(project_is_current("北极星计划", False, 2027))

    def test_blank_name_is_dropped(self):
        self.assertFalse(project_is_current("", True, 2027))
        self.assertFalse(project_is_current(None, True, 2027))

    def test_cohort_year_rolls_in_may(self):
        """与 campus_cycle_backlog.current_cohort 同口径：5 月起滚到下一届。"""
        import datetime as dt
        self.assertEqual(cohort_year(dt.datetime(2026, 9, 4)), 2027)
        self.assertEqual(cohort_year(dt.datetime(2026, 5, 1)), 2027)
        self.assertEqual(cohort_year(dt.datetime(2026, 4, 30)), 2026)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    """按 URL 分派：导航 / banner / 岗位列表。"""

    def __init__(self, nav, banners, lists):
        self.nav, self.banners, self.lists = nav, banners, lists
        self.list_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        params = params or {}
        if "navigation" in url:
            return _Resp(self.nav)
        if "banner" in url:
            name = self.banners.get(params.get("projectId"))
            return _Resp({"code": 200, "data": {"projectName": name} if name else None})
        self.list_calls.append(params)
        pages = self.lists.get(params.get("projectId"), [])
        page = params.get("currentPage", 1)
        if page <= len(pages):
            return _Resp(pages[page - 1])
        return _Resp({"code": 200, "data": {"total": 0, "list": []}})


def _page(ids, total):
    return {"code": 200, "data": {"total": total, "list": [
        {"id": i, "positionName": f"岗{i}", "workPlaceName": "杭州,上海",
         "positionTypeName": "技术", "positionDescription": "职责" * 20,
         "positionRequirement": "要求" * 20} for i in ids]}}


def _nav(ids):
    return {"code": 200, "data": [
        {"title": "应届生", "children": [
            {"title": f"p{i}", "link": f"https://campus.163.com/app/job/position?id={i}"} for i in ids]}]}


class NeteaseCampusFetchTest(unittest.TestCase):
    def _run(self, nav, banners, lists, page_size=2):
        adapter = NeteaseCampusAdapter()
        adapter.PAGE_SIZE = page_size
        adapter.SCAN_BACK, adapter.SCAN_AHEAD = 3, 2
        client = _FakeClient(nav, banners, lists)
        with mock.patch.object(netease_campus.httpx, "Client", lambda **kw: client):
            jobs = adapter.parse(adapter.fetch("https://campus.163.com/app/job"))
        return adapter, jobs, client

    def test_only_current_projects_are_fetched(self):
        adapter, jobs, client = self._run(
            _nav([103]),
            {101: "2026届互联网校招-秋招", 102: "测试test-互娱测试项目",
             103: "网易互联网2027届校园招聘", 104: "网易互娱2028届实习生项目"},
            {101: [_page([91, 92], 2)], 102: [_page([81], 1)],
             103: [_page([1, 2], 3), _page([3], 3)], 104: [_page([7], 1)]})
        fetched = {c["projectId"] for c in client.list_calls}
        self.assertEqual(fetched, {103, 104})          # 过期项目和测试项目一个都不许碰
        self.assertEqual([j.title for j in jobs], ["岗1", "岗2", "岗3", "岗7"])
        self.assertEqual(adapter.reported_total, 4)
        self.assertTrue(adapter.fetch_complete)

    def test_project_not_drained_blocks_complete(self):
        adapter, _jobs, _c = self._run(
            _nav([103]), {103: "网易互联网2027届校园招聘"}, {103: [_page([1, 2], 99)]})
        self.assertFalse(adapter.fetch_complete)

    def test_jd_url_uses_list_id_and_is_unique(self):
        _a, jobs, _c = self._run(
            _nav([103]), {103: "网易互联网2027届校园招聘"}, {103: [_page([4860, 4861], 2)]})
        self.assertEqual(jobs[0].jd_url, "https://campus.163.com/app/detail/index?id=4860")
        self.assertEqual(len({j.jd_url for j in jobs}), len(jobs))

    def test_navigation_failure_falls_back_to_cohort_rule(self):
        """导航挂了不致命：窗口扫描 + 届次规则仍要能选出当前项目。"""
        adapter = NeteaseCampusAdapter()
        adapter.PAGE_SIZE, adapter.SCAN_BACK, adapter.SCAN_AHEAD = 2, 1, 1
        adapter.FALLBACK_ANCHOR = 103
        client = _FakeClient({"data": None}, {103: "网易互联网2027届校园招聘"},
                             {103: [_page([1], 1)]})
        with mock.patch.object(netease_campus.httpx, "Client", lambda **kw: client):
            jobs = adapter.parse(adapter.fetch("https://campus.163.com/app/job"))
        self.assertEqual([j.title for j in jobs], ["岗1"])

    def test_no_current_project_raises_instead_of_silent_empty(self):
        adapter = NeteaseCampusAdapter()
        adapter.SCAN_BACK, adapter.SCAN_AHEAD = 1, 1
        client = _FakeClient(_nav([103]), {103: "2026届互联网校招-秋招"}, {})
        with mock.patch.object(netease_campus.httpx, "Client", lambda **kw: client):
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://campus.163.com/app/job")

    def test_multi_city_kept_in_summary_first_as_location(self):
        _a, jobs, _c = self._run(_nav([103]), {103: "网易互联网2027届校园招聘"},
                                 {103: [_page([1], 1)]})
        self.assertEqual(jobs[0].location, "杭州")
        self.assertIn("杭州,上海", jobs[0].summary)


if __name__ == "__main__":
    unittest.main()
