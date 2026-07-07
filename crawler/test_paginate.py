"""paginate_all 分页 helper 单测（纯函数，不打真实网络）。

覆盖两类停止条件：
  - 已知 total（tencent 范式）：翻到 collected >= total。
  - 未知 total（jd 范式）：翻到末页（本页 < page_size）或空页。
外加安全上限、首页/后续页异常语义、offset/page 索引映射。
"""
import logging
import unittest

from adapters.base import paginate_all, PageResult


def _pager(pages):
    """把「页号→PageResult」的列表包装成 fetch_page 闭包，并记录被请求的页号序列。

    pages[i] 供第 i 次调用（0-based）。索引越界返回空页（total 沿用最后一页给的）。
    """
    calls = []

    def fetch_page(page_index):
        calls.append(page_index)
        idx = len(calls) - 1
        if idx < len(pages):
            return pages[idx]
        return PageResult(items=[], total=None)

    return fetch_page, calls


class PaginateKnownTotalTests(unittest.TestCase):
    def test_known_total_exact_multiple(self):
        # total=200, page_size=100 → 恰好两满页收满。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=200),
            PageResult(items=list(range(100)), total=200),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 200)
        self.assertEqual(total, 200)
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2])  # 收满即停，不多打一页

    def test_known_total_partial_last_page(self):
        # total=150 → 第二页只有 50 条，收满即停。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=150),
            PageResult(items=list(range(50)), total=150),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 150)
        self.assertEqual(total, 150)
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2])

    def test_total_read_from_later_page(self):
        # 首页没给 total，第二页才给 → 以首个非空 total 为准。
        fetch_page, _ = _pager([
            PageResult(items=list(range(100)), total=None),
            PageResult(items=list(range(20)), total=120),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 120)
        self.assertEqual(total, 120)
        self.assertTrue(complete)

    def test_known_total_underfetch_marks_incomplete(self):
        # API 自报 300，但第二页就空了 → 只拿到 100，诚实标 complete=False。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=300),
            PageResult(items=[], total=300),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 100)
        self.assertEqual(total, 300)
        self.assertFalse(complete)
        self.assertEqual(calls, [1, 2])


class PaginateUnknownTotalTests(unittest.TestCase):
    def test_unknown_total_stops_on_short_page(self):
        # 接口不报 total → 本页 < page_size 视为末页，total 记为已抓数。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=None),
            PageResult(items=list(range(30)), total=None),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 130)
        self.assertEqual(total, 130)
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2])

    def test_unknown_total_stops_on_empty_page(self):
        # 满页后下一页恰好空 → 自然收尾，complete=True。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=None),
            PageResult(items=[], total=None),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 100)
        self.assertEqual(total, 100)
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2])

    def test_single_short_page(self):
        fetch_page, calls = _pager([
            PageResult(items=list(range(5)), total=None),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 5)
        self.assertEqual(total, 5)
        self.assertTrue(complete)
        self.assertEqual(calls, [1])


class PaginateSafetyCapTests(unittest.TestCase):
    def test_safety_cap_stops_and_warns_incomplete(self):
        # 恶意/异常接口：每页都满、total 一直大 → 到 max_pages 停，complete=False + 告警。
        def fetch_page(page_index):
            return PageResult(items=list(range(100)), total=10_000)

        logger = logging.getLogger("test_paginate_cap")
        with self.assertLogs(logger, level="WARNING") as cm:
            items, total, complete = paginate_all(
                fetch_page, page_size=100, max_pages=3, logger=logger, label="demo",
            )
        self.assertEqual(len(items), 300)  # 只抓了 3 页
        self.assertFalse(complete)
        self.assertTrue(any("cap" in m.lower() or "上限" in m for m in cm.output))


class PaginateTotalPagesTests(unittest.TestCase):
    """接口只报 totalPage（页数）而无 item 总数、且中间页可能「短页」时（hotjob 范式）：
    应按页数翻到底，不被短页误判为末页。"""

    def test_total_pages_drives_stop(self):
        # totalPage=3、每页满页 → 翻满 3 页即停，complete=True。
        fetch_page, calls = _pager([
            PageResult(items=list(range(20)), total=None, total_pages=3),
            PageResult(items=list(range(20)), total=None, total_pages=3),
            PageResult(items=list(range(20)), total=None, total_pages=3),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=20)
        self.assertEqual(len(items), 60)
        self.assertTrue(complete)
        self.assertEqual(total, 60)     # 无 item 总数 → 收满后诚实以已抓数为分母
        self.assertEqual(calls, [1, 2, 3])

    def test_total_pages_ignores_ragged_short_page(self):
        # totalPage=3，但第 1 页因限流/瞬时只回了 5 条（短页）——不能据此判末页，必须继续翻到第 3 页。
        fetch_page, calls = _pager([
            PageResult(items=list(range(5)),  total=None, total_pages=3),   # 短页但非末页
            PageResult(items=list(range(20)), total=None, total_pages=3),
            PageResult(items=list(range(18)), total=None, total_pages=3),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=20)
        self.assertEqual(len(items), 43)   # 5 + 20 + 18，一条不丢
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2, 3])

    def test_total_pages_empty_page_ends_early(self):
        # totalPage 说 4 页，但第 2 页就空了（服务端实际提前没货）→ 自然收尾 complete=True。
        fetch_page, calls = _pager([
            PageResult(items=list(range(20)), total=None, total_pages=4),
            PageResult(items=[],              total=None, total_pages=4),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=20)
        self.assertEqual(len(items), 20)
        self.assertTrue(complete)
        self.assertEqual(calls, [1, 2])


class PaginateIndexingTests(unittest.TestCase):
    def test_first_page_zero_based_offset(self):
        # offset 型 adapter：first_page=0，闭包自己把 page_index 映射成 offset。
        fetch_page, calls = _pager([
            PageResult(items=list(range(100)), total=120),
            PageResult(items=list(range(20)), total=120),
        ])
        items, total, complete = paginate_all(fetch_page, page_size=100, first_page=0)
        self.assertEqual(len(items), 120)
        self.assertTrue(complete)
        self.assertEqual(calls, [0, 1])  # 0-based 递增


class PaginateErrorTests(unittest.TestCase):
    def test_first_page_exception_propagates(self):
        # 首页失败 → 抛出，交给上层记 failed（不吞）。
        def fetch_page(page_index):
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            paginate_all(fetch_page, page_size=100)

    def test_later_page_exception_keeps_partial(self):
        # 后续页失败 → 保留已抓、标 complete=False，不炸穿。
        def fetch_page(page_index):
            if page_index == 1:
                return PageResult(items=list(range(100)), total=500)
            raise RuntimeError("transient")

        items, total, complete = paginate_all(fetch_page, page_size=100)
        self.assertEqual(len(items), 100)
        self.assertFalse(complete)


if __name__ == "__main__":
    unittest.main()
