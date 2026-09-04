"""顺丰 adapter：限流/短页时「尽力而为」，不许把整源扔掉。

2026-09-04 线上实测：抬掉 50 页硬顶之后，CI 上第 43 页开始返 `listObj: None`（顺丰按量限流），
旧写法在那里 raise → 整源 failed、**已经抓到的 420 个在招岗一起丢掉**；
紧接着下一轮 HEAD 预检又因为刚被限流而 skip，于是连着两条 crawl_run 一个岗都没入。
末页那次更离谱：expected_rows 是按首页 totalResult 算的，翻 217 页要几分钟、期间上下架
必然让真实总数漂移（expected 6 got 4），2,164 个岗因为差 2 条全丢。

规矩（与 base.paginate_all 同口径）：首页失败才上抛记 failed；后续页失败保留已抓到的、
停止、让 fetch_complete 如实记「没抓全」。少抓几条和扔掉整源，代价差三个数量级。
"""
import json
import unittest
from unittest.mock import patch

from adapters import sf_express as sf_mod
from adapters.sf_express import SfExpressAdapter


def _page(rows, total_pages=3, total_result=25):
    return {"JobSearchList": {"listObj": rows, "totalPage": total_pages,
                              "totalResult": total_result, "showCount": 10}}


def _rows(start, n):
    return [{"id": str(start + i), "positionType": "3", "positionName": f"岗{start+i}",
             "cityName": "深圳"} for i in range(n)]


class _Client:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, **kw):
        idx = (json or {}).get("currentPage", 1) - 1
        self.calls += 1
        payload = self.pages[idx] if idx < len(self.pages) else _page(None)
        return _Resp(payload)


class _Resp:
    def __init__(self, p):
        self._p = p

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class SfExpressPartialTest(unittest.TestCase):
    def _fetch(self, pages):
        adapter = SfExpressAdapter()
        adapter.regions = ["CN"]
        with patch.object(sf_mod.httpx, "Client", lambda **kw: _Client(pages)), \
             patch.object(sf_mod.time, "sleep", lambda *_: None):
            return adapter, json.loads(adapter.fetch("https://hr.sf-express.com/x"))

    def test_rate_limited_mid_crawl_keeps_what_it_got(self):
        """第 2 页起被限流（listObj=None）→ 保留第 1 页的 10 条，不抛异常。"""
        adapter, blob = self._fetch([_page(_rows(1, 10)), _page(None), _page(None)])
        self.assertEqual(len(blob["jobs"]), 10)
        self.assertFalse(adapter.fetch_complete, "没抓全必须如实记，否则 list-absence 会误杀")
        self.assertEqual(adapter.reported_total, 25, "分母仍按官网自报记，缺口才看得见")

    def test_short_last_page_does_not_kill_the_source(self):
        """末页比按首页 totalResult 算出来的少（对方在我们翻页期间下架了岗）不是失败。"""
        adapter, blob = self._fetch([_page(_rows(1, 10)), _page(_rows(11, 10)),
                                     _page(_rows(21, 3))])   # 期望 5 条，实到 3 条
        self.assertEqual(len(blob["jobs"]), 23)
        self.assertFalse(adapter.fetch_complete)

    def test_first_page_failure_still_raises(self):
        """首页就拿不到数据 = 接口坏了，必须上抛让 run.py 记 failed，不许伪装成功。"""
        adapter = SfExpressAdapter()
        adapter.regions = ["CN"]
        with patch.object(sf_mod.httpx, "Client", lambda **kw: _Client([_page(None)])), \
             patch.object(sf_mod.time, "sleep", lambda *_: None):
            with self.assertRaises(RuntimeError):
                adapter.fetch("https://hr.sf-express.com/x")

    def test_full_crawl_marks_complete(self):
        adapter, blob = self._fetch([_page(_rows(1, 10)), _page(_rows(11, 10)), _page(_rows(21, 5))])
        self.assertEqual(len(blob["jobs"]), 25)
        self.assertTrue(adapter.fetch_complete)


if __name__ == "__main__":
    unittest.main()
