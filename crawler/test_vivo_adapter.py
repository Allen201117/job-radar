import json
import unittest
from unittest.mock import patch

from adapters.vivo import VivoAdapter


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, pages):
        self._pages = list(pages)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        if not self._pages:
            raise AssertionError(f"unexpected POST {url}")
        return _FakeResponse(self._pages.pop(0))


def _page(page_no, total, ids):
    # 2026-09-13 live 响应形状：总数在 meta.total，body 顶层与 data（是 list）里都没有。
    return {
        "code": 0,
        "message": "success",
        "success": True,
        "data": [{"job_id": i} for i in ids],
        "meta": {"page": page_no, "total": total, "page_count": 2, "max_results": 2},
    }


class VivoReportedTotalTest(unittest.TestCase):
    def _fetch(self, pages):
        adapter = VivoAdapter()
        adapter.PAGE_SIZE = 2
        with patch("adapters.vivo.httpx.Client", return_value=_FakeClient(pages)):
            payload = adapter.fetch("https://hr.vivo.com/jobs")
        return adapter, json.loads(payload)["data"]

    def test_reads_total_from_meta_and_marks_complete(self):
        adapter, rows = self._fetch([_page(1, 3, ["a", "b"]), _page(2, 3, ["c"])])

        self.assertEqual(len(rows), 3)
        self.assertEqual(adapter.reported_total, 3)
        self.assertTrue(adapter.fetch_complete)

    def test_short_first_page_below_meta_total_is_not_complete(self):
        # 短页被当成末页时，只有拿到 meta.total 才看得出「没抓全」（规则 G 靠它告警）。
        adapter, rows = self._fetch([_page(1, 5, ["a"])])

        self.assertEqual(len(rows), 1)
        self.assertEqual(adapter.reported_total, 5)
        self.assertFalse(adapter.fetch_complete)


class VivoAdapterTest(unittest.TestCase):
    def test_parse_maps_job_ids_to_verified_detail_url(self):
        payload = {
            "data": [{
                "job_id": "M1815270404823314433",
                "job_code": "M1898Q",
                "job_title": "3D算法专家",
                "job_location_list": [{"city": "杭州"}],
                "job_category_id": "M1718986166464483330",
                "job_category": "研发类",
                "job_desc": "负责移动终端空间感知技术。",
            }]
        }

        jobs = VivoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "vivo")
        self.assertEqual(jobs[0].title, "3D算法专家（M1898Q）")
        self.assertEqual(
            jobs[0].jd_url,
            "https://hr.vivo.com/job-detail"
            "?_irjc=M1718986166464483330"
            "&_irjid=M1815270404823314433&_collect=false",
        )


if __name__ == "__main__":
    unittest.main()
