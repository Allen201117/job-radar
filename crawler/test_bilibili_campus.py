"""bilibili_campus 单测（mock httpx，不打真网络）。

红线：
① 校招/实习**两个桶必须分别翻并合并** —— live 实测不传 positionTypeList 拿到的不是并集
   （不传 100 / Freshmen 91 / Intern 281），只翻一个桶会漏掉一大半；
② 任一桶没翻干净就不许 fetch_complete=True；
③ jd_url 只用列表行的 id 拼 /campus/positions/{id}（2026-09-04 live 核过页面渲染的正是该岗）。
"""
import json
import unittest
from unittest import mock

from adapters import bilibili_campus
from adapters.bilibili_campus import BilibiliCampusAdapter


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        return None


class _FakeClient:
    """按 positionTypeList 取值分桶返回；记录收到的每个请求体供断言。"""

    def __init__(self, by_bucket):
        self.by_bucket = by_bucket
        self.seen_bodies = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        return _Resp({"code": 0, "data": "csrf-token-abc"})

    def post(self, url, json=None, headers=None):
        self.seen_bodies.append(json)
        bucket = (json.get("positionTypeList") or [""])[0]
        pages = self.by_bucket.get(bucket, [])
        page_no = json.get("pageNum", 1)
        if page_no <= len(pages):
            return _Resp(pages[page_no - 1])
        return _Resp({"code": 0, "data": {"list": [], "total": 0}})


def _page(ids, total):
    return {"code": 0, "data": {"total": total, "list": [
        {"id": i, "positionName": f"岗{i}", "workLocation": "上海",
         "positionDescription": "职责与要求" * 12, "positionTypeName": "全职"} for i in ids]}}


def _patch(by_bucket):
    client = _FakeClient(by_bucket)
    return client, mock.patch.object(bilibili_campus.httpx, "Client", lambda **kw: client)


class BilibiliCampusTest(unittest.TestCase):
    def _a(self, page_size=2):
        a = BilibiliCampusAdapter()
        a.PAGE_SIZE = page_size
        return a

    def test_merges_both_buckets_and_reports_their_sum(self):
        a = self._a()
        client, patcher = _patch({"3": [_page([1, 2], 3), _page([3], 3)], "0": [_page([7, 8], 2)]})
        with patcher:
            jobs = a.parse(a.fetch("https://jobs.bilibili.com/campus/positions"))
        self.assertEqual([j.title for j in jobs], ["岗1", "岗2", "岗3", "岗7", "岗8"])
        self.assertEqual(a.reported_total, 5)          # 3(校招) + 2(实习)
        self.assertTrue(a.fetch_complete)
        buckets = [(b.get("positionTypeList") or [None])[0] for b in client.seen_bodies]
        self.assertIn("3", buckets)
        self.assertIn("0", buckets)

    def test_one_bucket_not_drained_blocks_complete(self):
        """实习桶自报 99 只给 2 条 → 整源不许标抓全（否则抓全率观测会说谎）。"""
        a = self._a()
        _, patcher = _patch({"3": [_page([1, 2], 2)], "0": [_page([7, 8], 99)]})
        with patcher:
            a.fetch("https://jobs.bilibili.com/campus/positions")
        self.assertFalse(a.fetch_complete)

    def test_jd_url_uses_list_id(self):
        a = self._a()
        _, patcher = _patch({"3": [_page([29738], 1)], "0": [_page([], 0)]})
        with patcher:
            jobs = a.parse(a.fetch("https://jobs.bilibili.com/campus/positions"))
        self.assertEqual(jobs[0].jd_url, "https://jobs.bilibili.com/campus/positions/29738")
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)

    def test_ids_are_deduped_across_buckets(self):
        """同一个岗可能同时命中两个桶；按 id 去重，别入库两行。"""
        a = self._a()
        _, patcher = _patch({"3": [_page([1, 2], 2)], "0": [_page([2, 3], 2)]})
        with patcher:
            jobs = a.parse(a.fetch("https://jobs.bilibili.com/campus/positions"))
        self.assertEqual([j.title for j in jobs], ["岗1", "岗2", "岗3"])

    def test_empty_list_raises_not_silently_empty(self):
        a = self._a()
        _, patcher = _patch({})
        with patcher:
            with self.assertRaises(RuntimeError):
                a.fetch("https://jobs.bilibili.com/campus/positions")

    def test_non_china_location_is_dropped(self):
        a = self._a()
        _, patcher = _patch({"3": [{"code": 0, "data": {"total": 1, "list": [
            {"id": 5, "positionName": "岗5", "workLocation": "Singapore",
             "positionDescription": "x" * 80}]}}], "0": [_page([], 0)]})
        with patcher:
            jobs = a.parse(a.fetch("https://jobs.bilibili.com/campus/positions"))
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
