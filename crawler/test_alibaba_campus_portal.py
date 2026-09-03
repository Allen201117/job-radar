"""alibaba_campus_portal 单测（mock httpx，不打真网络）。

红线：
① 阿里星与应届生**共用 batchId**，不去重整批岗会被抓两遍；
② 会话是 CSRF 不是登录——拿不到 XSRF-TOKEN 必须显式报错，不能静默出 0 岗；
③ `circleNames`（可投 BU 列表，一个岗常挂 13 个）绝不能拿来派生 company。
"""
import json
import unittest
from unittest import mock

from adapters import alibaba_campus_portal as m
from adapters.alibaba_campus_portal import AlibabaCampusPortalAdapter


class BatchIdsTest(unittest.TestCase):
    def test_alistar_sharing_graduate_batch_id_is_deduped(self):
        payload = {"content": {
            "graduate": [{"id": 100000760001, "name": "阿里巴巴2027届应届生"}],
            "internship": [{"id": 100000560002}, {"id": 100000560001}],
            "topTalentPlan": [{"id": 100000760001, "name": "阿里星-27届应届生"}]}}
        self.assertEqual(AlibabaCampusPortalAdapter.batch_ids(payload),
                         [100000760001, 100000560002, 100000560001])

    def test_missing_or_bad_ids_are_skipped(self):
        payload = {"content": {"graduate": [{"name": "无 id"}, {"id": "abc"}, {"id": 7}]}}
        self.assertEqual(AlibabaCampusPortalAdapter.batch_ids(payload), [7])

    def test_empty_payload_returns_empty(self):
        self.assertEqual(AlibabaCampusPortalAdapter.batch_ids(None), [])
        self.assertEqual(AlibabaCampusPortalAdapter.batch_ids({"content": None}), [])


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, batches, pages_by_batch, token="tok-123"):
        self.cookies = {"XSRF-TOKEN": token} if token else {}
        self.batches, self.pages_by_batch = batches, pages_by_batch
        self.searched = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        return _Resp({})

    def post(self, url, params=None, json=None):
        if "listBatch" in url:
            return _Resp(self.batches)
        self.searched.append(json)
        pages = self.pages_by_batch.get(json["batchId"], [])
        idx = json["pageIndex"]
        if idx <= len(pages):
            return _Resp(pages[idx - 1])
        return _Resp({"success": True, "content": {"totalCount": 0, "datas": []}})


def _page(ids, total, status="recruit"):
    return {"success": True, "content": {"totalCount": total, "datas": [
        {"id": i, "name": f"岗{i}", "status": status, "workLocations": ["杭州", "北京"],
         "categoryName": "技术类", "batchName": "阿里巴巴2027届应届生",
         "description": "描述" * 30, "requirement": "要求" * 30,
         "circleNames": ["阿里云", "淘天集团", "高德地图"]} for i in ids]}}


def _batches(ids):
    return {"content": {"graduate": [{"id": ids[0]}],
                        "internship": [{"id": i} for i in ids[1:]],
                        "topTalentPlan": [{"id": ids[0]}]}}


class FetchTest(unittest.TestCase):
    def _run(self, batches, pages, token="tok-123", page_size=2):
        adapter = AlibabaCampusPortalAdapter()
        adapter.PAGE_SIZE = page_size
        client = _FakeClient(batches, pages, token)
        with mock.patch.object(m.httpx, "Client", lambda **kw: client):
            html = adapter.fetch("https://campus-talent.alibaba.com/campus/position")
        return adapter, adapter.parse(html), client

    def test_each_batch_fetched_once_and_totals_summed(self):
        adapter, jobs, client = self._run(
            _batches([1, 2]), {1: [_page([10, 11], 3), _page([12], 3)], 2: [_page([20], 1)]})
        self.assertEqual([j.title for j in jobs], ["岗10", "岗11", "岗12", "岗20"])
        self.assertEqual(adapter.reported_total, 4)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(sorted({c["batchId"] for c in client.searched}), [1, 2])

    def test_missing_csrf_token_raises_instead_of_silent_empty(self):
        with self.assertRaises(RuntimeError):
            self._run(_batches([1]), {1: [_page([10], 1)]}, token=None)

    def test_no_batches_raises(self):
        with self.assertRaises(RuntimeError):
            self._run({"content": {}}, {})

    def test_batch_not_drained_blocks_complete(self):
        adapter, _jobs, _c = self._run(_batches([1]), {1: [_page([10, 11], 99)]})
        self.assertFalse(adapter.fetch_complete)

    def test_non_recruiting_rows_are_dropped(self):
        _a, jobs, _c = self._run(_batches([1]), {1: [_page([10], 1, status="closed")]})
        self.assertEqual(jobs, [])

    def test_company_never_derived_from_circle_names(self):
        """circleNames 是「这个岗可投哪些 BU」，不是岗位归属；拿它派生 company 会把一个岗拆成十几家。"""
        _a, jobs, _c = self._run(_batches([1]), {1: [_page([10], 1)]})
        self.assertEqual({j.company for j in jobs}, {"阿里巴巴"})

    def test_jd_url_uses_list_id_not_position_url(self):
        _a, jobs, _c = self._run(_batches([1]), {1: [_page([199907740040], 1)]})
        self.assertEqual(jobs[0].jd_url,
                         "https://campus-talent.alibaba.com/campus/position/199907740040")

    def test_all_work_locations_kept_in_summary(self):
        _a, jobs, _c = self._run(_batches([1]), {1: [_page([10], 1)]})
        self.assertEqual(jobs[0].location, "杭州")
        self.assertIn("杭州 / 北京", jobs[0].summary)


if __name__ == "__main__":
    unittest.main()
