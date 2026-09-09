"""lixiang_campus adapter 单测。

理想校招/实习走自建站 api-web.lixiang.com，与 li.jobs.feishu.cn（社招）完全是两条线。
重点钉死三件容易悄悄坏掉的事：
  ① hire_mode 参数被服务端忽略——校招/实习必须靠列表自带的 job_mode 区分，不能拆参数；
  ② fetch_complete 必须按「一级分类」逐渠道判抓全（同 huawei_campus/xiaohongshu 口径）；
  ③ job/function 返回 200 + 空 data 时必须抛错，不许安静判「理想没开校招」。
"""
import json
import os
import unittest
from unittest.mock import patch

from adapters import lixiang_campus as lx_mod
from adapters.lixiang_campus import LixiangCampusAdapter


def _function_payload(categories):
    return {"data": {"list": categories}, "code": 0}


def _category(cat_id, title, job_count, leaf_ids):
    return {"id": cat_id, "title": title, "job_count": job_count,
            "list": [{"id": i, "title": f"leaf{i}"} for i in leaf_ids]}


def _list_payload(total_pages, items):
    return {"data": {"page": 1, "total_pages": total_pages, "items": items}, "code": 0}


def _item(job_id, title, job_mode="201", job_mode_name="正式", code="A1", location="北京"):
    return {"id": job_id, "title": title, "code": code, "job_mode": job_mode,
            "job_mode_name": job_mode_name, "location_title": location,
            "first_job_function_title": "算法与软件", "second_job_function_title": "算法",
            "hire_mode": 2}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    """按 URL 路由的假 client：job/function 一次性返分类；job-page 按 (leaf_ids, page) 出队；
    job/detail 按 job_id 出详情。"""

    def __init__(self, function_payload, list_pages_by_ids, detail_by_id=None):
        self.function_payload = function_payload
        self.list_pages_by_ids = list_pages_by_ids  # {ids_param: [payload, payload, ...]}  按 page 顺序出队
        self._list_cursor = {}
        self.detail_by_id = detail_by_id or {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **kw):
        params = params or {}
        self.calls.append((url, params))
        if url == lx_mod._FUNCTION_API:
            return _Resp(self.function_payload)
        if url == lx_mod._LIST_API:
            ids = params["job_function_ids"]
            queue = self.list_pages_by_ids.get(ids) or []
            idx = self._list_cursor.get(ids, 0)
            payload = queue[idx] if idx < len(queue) else _list_payload(idx, [])
            self._list_cursor[ids] = idx + 1
            return _Resp(payload)
        if url == lx_mod._DETAIL_API:
            job_id = params["job_id"]
            return _Resp({"data": self.detail_by_id.get(job_id, {}), "code": 0})
        raise AssertionError(f"unexpected GET {url}")


class LixiangCampusTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)
        os.environ.pop("CRAWL_MAX_JOBS", None)

    tearDown = setUp

    def _run(self, client):
        adapter = LixiangCampusAdapter()
        adapter.regions = ["CN"]
        with patch.object(lx_mod.httpx, "Client", lambda **kw: client):
            raw = adapter.fetch("https://www.lixiang.com/employ/campus.html?fromJob=1")
        return adapter, adapter.parse(raw)

    def test_jd_url_uses_id_and_code(self):
        cats = [_category(1, "算法与软件", 1, [10])]
        client = _FakeClient(
            _function_payload(cats),
            {"10": [_list_payload(1, [_item(18946, "算法实习生", code="A77805")])]},
        )
        _, jobs = self._run(client)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].jd_url,
                         "https://www.lixiang.com/employ/detail/18946.html?jobCode=A77805&fromJob=1")
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)

    def test_job_mode_drives_job_type_not_hire_mode(self):
        """hire_mode 恒为 2、被服务端忽略——job_type 只能来自 job_mode。"""
        cats = [_category(1, "算法与软件", 2, [10])]
        client = _FakeClient(
            _function_payload(cats),
            {"10": [_list_payload(1, [
                _item(1, "正式岗", job_mode="201", job_mode_name="正式"),
                _item(2, "实习岗", job_mode="202", job_mode_name="实习"),
            ])]},
        )
        _, jobs = self._run(client)
        by_title = {j.title: j.job_type for j in jobs}
        self.assertEqual(by_title["正式岗"], "校园招聘")
        self.assertEqual(by_title["实习岗"], "实习")

    def test_fetch_complete_requires_all_categories_drained(self):
        cats = [_category(1, "A", 1, [10]), _category(2, "B", 1, [20])]
        client = _FakeClient(
            _function_payload(cats),
            {
                "10": [_list_payload(1, [_item(1, "岗A")])],
                "20": [_list_payload(1, [_item(2, "岗B")])],
            },
        )
        adapter, jobs = self._run(client)
        self.assertEqual(adapter.reported_total, 2)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(len(jobs), 2)

    def test_short_category_marks_incomplete(self):
        """自报 job_count 与实抓条数对不上（如撞了安全上限/接口截断）→ 该渠道不算抓全。"""
        cats = [_category(1, "A", 99, [10])]
        client = _FakeClient(
            _function_payload(cats),
            {"10": [_list_payload(1, [_item(1, "岗A")])]},  # 只有 1 条，但自报 99
        )
        adapter, _ = self._run(client)
        self.assertFalse(adapter.fetch_complete)

    def test_empty_function_list_raises_instead_of_pretending_no_campus(self):
        """job/function 返 200 + 空 data 必须抛错记 failed，不许安静判「理想没开校招」。"""
        client = _FakeClient(_function_payload([]), {})
        adapter = LixiangCampusAdapter()
        adapter.regions = ["CN"]
        with patch.object(lx_mod.httpx, "Client", lambda **kw: client):
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://www.lixiang.com/employ/campus.html?fromJob=1")

    def test_dedup_across_categories_by_id(self):
        """叶子 id 分区理论上不重叠，但全局按 id 去重仍作兜底。"""
        cats = [_category(1, "A", 1, [10]), _category(2, "B", 1, [20])]
        client = _FakeClient(
            _function_payload(cats),
            {
                "10": [_list_payload(1, [_item(1, "岗A")])],
                "20": [_list_payload(1, [_item(1, "岗A")])],  # 故意重复 id
            },
        )
        _, jobs = self._run(client)
        self.assertEqual(len(jobs), 1)

    def test_detail_enrichment_populates_summary(self):
        cats = [_category(1, "A", 1, [10])]
        client = _FakeClient(
            _function_payload(cats),
            {"10": [_list_payload(1, [_item(1, "岗A")])]},
            detail_by_id={1: {"description": "<p>研究方向A</p>", "requirements": "<p>要求B</p>",
                              "department_title": "算力资源", "subject_name": "2026校园招聘"}},
        )
        _, jobs = self._run(client)
        summary = jobs[0].summary or ""
        self.assertIn("研究方向A", summary)
        self.assertIn("要求B", summary)
        self.assertIn("算力资源", summary)
        self.assertIn("2026校园招聘", summary)

    def test_detail_cap_zero_skips_enrichment_but_still_yields_thin_card(self):
        """daily 快档 CRAWL_DETAIL_CAP=0：不逐岗富化，仍要出骨架卡（薄卡由 enrich 链路后补）。"""
        os.environ["CRAWL_DETAIL_CAP"] = "0"
        cats = [_category(1, "A", 1, [10])]
        client = _FakeClient(
            _function_payload(cats),
            {"10": [_list_payload(1, [_item(1, "岗A")])]},
            detail_by_id={1: {"description": "<p>不该出现</p>"}},
        )
        _, jobs = self._run(client)
        self.assertEqual(len(jobs), 1)
        self.assertNotIn("不该出现", jobs[0].summary or "")

    def test_should_skip_returns_none(self):
        """公开 JSON 网关，HEAD 预检对它无意义——整源不能被 should_skip 静默跳过。"""
        adapter = LixiangCampusAdapter()
        self.assertIsNone(adapter.should_skip("https://www.lixiang.com/employ/campus.html?fromJob=1"))

    def test_referer_header_present(self):
        headers = LixiangCampusAdapter()._headers()
        self.assertEqual(headers.get("Referer"), "https://www.lixiang.com/")


if __name__ == "__main__":
    unittest.main()
