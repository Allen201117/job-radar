"""顺丰校招 adapter + 逐岗探活器单测（离线夹具，不打真实网络）。

三组重点，缺一条都等于拆掉一道安全网：
  ① parse：jd_url 用的是站点自己那条 hash 路由、地区门按 sources.regions 走、
     summary 段序保证届别（grad_class 只看前 400 字）抽得到；
  ② 翻页：收尾靠接口自报的 total/pages，**短页不当末页**；撞上限必须 fetch_complete=False；
  ③ 判死：双条件，含糊信号一律不判死（这个源的 expired 次日会被 purge 永久删除）。
"""
import json
import os
import unittest
from unittest import mock

import enrich
from adapters import sf_express_campus as mod
from adapters.sf_express_campus import SfExpressCampusAdapter
from grad_class import extract_grad_class
from normalizer import clean_summary


def _row(job_id=2260, **over):
    row = {
        "id": job_id,
        "positionName": "Java开发工程师（顺丰科技）",
        "demandCity": "成都市,武汉市,深圳市",
        "educationName": "大学本科",
        "createDate": "2026-08-11 20:04:34",
        "positionTypeName": "研发类",
        "orgSourceName": "顺丰科技",
        "internTypeName": "",
        "seasonType": "2",
        "jobRequirement": "1、2027届本科及以上学历毕业生，计算机、软件工程及相关专业优先。",
        "postDuty": "1、执行业务功能模块的代码编写。",
        "otherRequirement": "",
    }
    row.update(over)
    return row


def _parse(rows):
    return SfExpressCampusAdapter().parse(json.dumps({"list": rows}, ensure_ascii=False))


class SfCampusParseTest(unittest.TestCase):
    def test_parse_maps_core_fields_and_site_own_hash_route(self):
        jobs = _parse([_row()])
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "顺丰")
        self.assertEqual(job.title, "Java开发工程师（顺丰科技）")
        # 多城市取第一个做筛选字段，全部城市写进 summary
        self.assertEqual(job.location, "成都市")
        self.assertIn("工作城市：成都市、武汉市、深圳市", job.summary)
        self.assertEqual(job.job_type, "校园招聘")
        self.assertEqual(job.education, "大学本科")
        self.assertEqual(job.posted_at, "2026-08-11")
        # jd_url = 站点自己在列表卡片上拼的 href（`#/postDetail/{id}`），不是我们猜的路径
        self.assertEqual(job.jd_url, "https://crs-pub.sf-express.com/#/postDetail/2260")
        self.assertEqual(job.apply_url, job.jd_url)

    def test_grad_class_survives_summary_truncation(self):
        """届别硬信号只写在 jobRequirement 里，而 grad_class 只看截断后的前 400 字。
        postDuty 特意造得很长——要求段若排在职责后面，这条就会抽不到届别。"""
        jobs = _parse([_row(postDuty="负责系统开发。" * 90)])
        self.assertEqual(
            extract_grad_class(jobs[0].title, jobs[0].job_type,
                               clean_summary(jobs[0].summary)),
            2027)

    def test_intern_type_name_wins_over_season_type(self):
        # 岗位级标注优先于招聘季级
        jobs = _parse([_row(internTypeName="日常实习", seasonType="2")])
        self.assertEqual(jobs[0].job_type, "日常实习")

    def test_season_type_3_is_internship(self):
        jobs = _parse([_row(internTypeName="", seasonType="3")])
        self.assertEqual(jobs[0].job_type, "实习")

    def test_nationwide_location_passes_region_gate(self):
        # 「全国」是顺丰管培生的真实取值，必须过地区门（否则整类岗被静默丢掉）
        jobs = _parse([_row(demandCity="全国")])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].location, "全国")

    def test_overseas_location_is_dropped_by_region_gate(self):
        self.assertEqual(_parse([_row(demandCity="Singapore")]), [])

    def test_taiwan_is_dropped_even_under_the_relaxed_gate(self):
        """台湾红线：能识别出国别码（TW）就走严格分支，放宽的是「识别不出」那一档。"""
        self.assertEqual(_parse([_row(demandCity="台北市")]), [])

    def test_unrecognized_location_is_kept_not_dropped(self):
        """证据不足 ≠ 证据相反。live 全集里 id=2328 的 demandCity 是空串，
        严格判据会把这个真·在招岗丢掉（2026-09-18 实测 120 行里 1 行）。"""
        jobs = _parse([_row(demandCity=""), _row(job_id=9, demandCity="昆山市")])
        self.assertEqual(len(jobs), 2)
        self.assertIsNone(jobs[0].location)
        self.assertEqual(jobs[1].location, "昆山市")

    def test_rows_without_id_or_title_are_skipped(self):
        self.assertEqual(_parse([_row(job_id=None), _row(positionName="  ")]), [])

    def test_malformed_payload_returns_empty(self):
        self.assertEqual(SfExpressCampusAdapter().parse("not json"), [])


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, pages):
        self.pages = pages          # {pageNum: payload}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def get(self, url, params=None):
        page = (params or {}).get("pageNum")
        self.calls.append(page)
        return _Resp(self.pages[page])


def _page(rows, total, pages):
    return {"list": rows, "total": total, "pages": pages}


def _run(pages):
    client = _FakeClient(pages)
    with mock.patch.object(mod.httpx, "Client", lambda *a, **k: client):
        adapter = SfExpressCampusAdapter()
        raw = adapter.fetch("https://crs-pub.sf-express.com/#/positionList")
    return adapter, json.loads(raw)["list"], client


class SfCampusFetchTest(unittest.TestCase):
    def test_drains_all_pages_and_reports_complete(self):
        size = SfExpressCampusAdapter.PAGE_SIZE
        p1 = [_row(i) for i in range(1, size + 1)]
        p2 = [_row(i) for i in range(size + 1, size + 4)]
        adapter, rows, client = _run({1: _page(p1, size + 3, 2), 2: _page(p2, size + 3, 2)})
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, size + 3)
        self.assertEqual(len(rows), size + 3)
        self.assertEqual(client.calls, [1, 2])

    def test_short_page_is_not_treated_as_last_page(self):
        """接口自报 pages=2 时，即使第 1 页短了也必须继续翻 —— 短页判末页是本仓库立过碑的坑。"""
        adapter, rows, client = _run({
            1: _page([_row(1), _row(2)], 4, 2),
            2: _page([_row(3), _row(4)], 4, 2),
        })
        self.assertEqual(client.calls, [1, 2])
        self.assertEqual(len(rows), 4)
        self.assertTrue(adapter.fetch_complete)

    def test_missing_rows_make_fetch_incomplete(self):
        """自报 total 比拿到的多（翻页期间上下架 / 被限流）→ 如实记没抓全，不许自称成功。"""
        adapter, rows, _ = _run({1: _page([_row(1), _row(2)], 9, 1)})
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 9)
        self.assertEqual(len(rows), 2)

    def test_duplicate_ids_across_pages_do_not_fake_completeness(self):
        """分页窗口滑动时两页可能撞同一条；去重后不够 total 就不算抓全。"""
        adapter, rows, _ = _run({
            1: _page([_row(1), _row(2)], 4, 2),
            2: _page([_row(2), _row(1)], 4, 2),
        })
        self.assertEqual(len(rows), 2)
        self.assertFalse(adapter.fetch_complete)

    def test_empty_season_is_a_legitimate_zero(self):
        adapter, rows, _ = _run({1: _page([], 0, 0)})
        self.assertEqual(rows, [])
        self.assertEqual(adapter.reported_total, 0)
        self.assertTrue(adapter.fetch_complete)

    def test_hitting_the_list_cap_is_never_reported_as_complete(self):
        """CRAWL_MAX_JOBS 压档时撞上限必须 fetch_complete=False —— base.resolve_list_cap 的
        文档字符串专门立过这条：撞上限还自称抓全，下游 list-absence 会把没抓到的尾巴当撤岗。"""
        size = SfExpressCampusAdapter.PAGE_SIZE
        pages = {n: _page([_row(i) for i in range((n - 1) * size, n * size)], 500, 10)
                 for n in range(1, 11)}
        with mock.patch.dict(os.environ, {"CRAWL_MAX_JOBS": "10"}):
            adapter, rows, client = _run(pages)
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(client.calls, [1])      # ceil(10/50) = 1 页就停
        self.assertEqual(adapter.reported_total, 500)

    def test_http_200_with_broken_shape_raises(self):
        """「HTTP 200 + 结构不对」必须记 failed，不许安静返 0 条。"""
        client = _FakeClient({1: {"msg": "ok"}})
        with mock.patch.object(mod.httpx, "Client", lambda *a, **k: client):
            with self.assertRaises(RuntimeError):
                SfExpressCampusAdapter().fetch("https://crs-pub.sf-express.com/#/positionList")


class _LiveResp:
    def __init__(self, payload=None, status=200, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class SfCampusLivenessTest(unittest.TestCase):
    _ROW = {"jd_url": "https://crs-pub.sf-express.com/#/postDetail/2260"}

    @staticmethod
    def _patch(resp):
        return mock.patch.object(enrich.httpx, "get", lambda *a, **k: resp)

    def test_live_status_1_is_not_closed(self):
        with self._patch(_LiveResp({"id": 2260, "positionName": "集团管培生", "status": 1})):
            self.assertEqual(enrich._detail_sf_express_campus(self._ROW, {}), "")

    def test_status_2_raises_job_closed(self):
        with self._patch(_LiveResp({"id": 2100, "positionName": "地面保障储备", "status": 2})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_status_0_raises_job_closed(self):
        with self._patch(_LiveResp({"id": 2267, "positionName": "语音大模型算法工程师", "status": 0})):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_id_not_found_500_raises_job_closed(self):
        with self._patch(_LiveResp({"message": "找不到职位信息", "status": 500}, status=500)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_plain_500_without_marker_is_unknown_not_closed(self):
        """真 5xx / 限流不是撤岗 —— 只看状态码判死会一轮清空整个源。"""
        with self._patch(_LiveResp({"message": "系统繁忙", "status": 500}, status=500)):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_half_payload_without_name_is_unknown_not_closed(self):
        """只剩 status、没有 positionName = 半截响应，既不判死也不算确认在招。"""
        with self._patch(_LiveResp({"status": 2})):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_non_json_is_unknown(self):
        with self._patch(_LiveResp(None, text="<html>waf</html>")):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_404_raises_job_closed_via_shared_convention(self):
        with self._patch(_LiveResp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_sf_express_campus(self._ROW, {})

    def test_jd_url_without_id_makes_no_request(self):
        calls = []

        def _get(*a, **k):
            calls.append(a)
            raise AssertionError("不该发请求")

        with mock.patch.object(enrich.httpx, "get", _get):
            self.assertEqual(
                enrich._detail_sf_express_campus({"jd_url": "https://crs-pub.sf-express.com/"}, {}), "")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
