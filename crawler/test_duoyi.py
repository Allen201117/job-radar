"""多益网络 adapter 离线单测（夹具复刻 2026-09-18 live 返回体形状，不打网络）。"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import duoyi  # noqa: E402
from adapters.base import PageResult  # noqa: E402

ROW_CAMPUS = {
    "id": "1674681784744284160", "category": "SCHOOL", "name": "游戏服务端开发工程师",
    "outerType": "程序类", "outerNature": ["正式"], "workPlaces": ["广州", "武汉", "杭州"],
    "jobResponsibility": "1、参与游戏服务端功能模块的设计与开发。",
    "jobRequirements": "1、计算机相关专业 2027 届毕业生；2、掌握至少一门编程语言。",
    "salaryRange": None, "publishDate": "2026-09-10",
}
ROW_INTERN = {**ROW_CAMPUS, "id": "1953059698848563200", "name": "灵活职业岗",
              "outerNature": ["实习"], "salaryRange": "3000元/月"}
ROW_TW = {**ROW_CAMPUS, "id": "9", "name": "台北岗", "workPlaces": ["台北市"]}


def _payload(rows, total):
    return {"message": "success", "data": {"pageIndex": 1, "pageSize": 100, "total": total, "list": rows}}


class ChannelTest(unittest.TestCase):
    def test_channel_follows_host_prefix_only(self):
        self.assertEqual(duoyi.channel_of("https://xz.duoyi.com/v40/#/positions"), 10)
        self.assertEqual(duoyi.channel_of("https://sz.duoyi.com/v40/sz-index.html"), 20)

    def test_unknown_host_raises_instead_of_guessing(self):
        with self.assertRaises(RuntimeError):
            duoyi.channel_of("https://www.duoyi.com/")


class ParseTest(unittest.TestCase):
    def _parse(self, rows, host="xz.duoyi.com", channel=10):
        a = duoyi.DuoyiAdapter()
        return a.parse(json.dumps({"host": host, "channel": channel, "rows": rows}, ensure_ascii=False))

    def test_campus_row_maps_fields_and_hash_route_jd_url(self):
        jobs = self._parse([ROW_CAMPUS])
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.company, "多益网络")
        self.assertEqual(j.title, "游戏服务端开发工程师")
        self.assertEqual(j.location, "广州")
        self.assertEqual(j.job_type, "校园招聘")
        self.assertEqual(j.jd_url, "https://xz.duoyi.com/v40/#/position-detail/1674681784744284160")
        self.assertEqual(j.posted_at, "2026-09-10")
        # 要求段排在职责段前（届别硬信号在要求段，grad_class 只看前 400 字）
        self.assertLess(j.summary.index("【任职要求】"), j.summary.index("【岗位职责】"))
        self.assertIn("工作城市：广州、武汉、杭州", j.summary)

    def test_intern_nature_wins_over_channel_and_social_channel_label(self):
        self.assertEqual(self._parse([ROW_INTERN])[0].job_type, "实习")
        self.assertEqual(self._parse([ROW_CAMPUS], host="sz.duoyi.com", channel=20)[0].job_type, "社会招聘")
        self.assertEqual(self._parse([ROW_CAMPUS], host="sz.duoyi.com", channel=20)[0].jd_url,
                         "https://sz.duoyi.com/v40/#/position-detail/1674681784744284160")

    def test_taiwan_location_is_dropped_but_bare_city_kept(self):
        titles = [j.title for j in self._parse([ROW_CAMPUS, ROW_TW])]
        self.assertEqual(titles, ["游戏服务端开发工程师"])

    def test_rows_without_id_or_title_are_skipped(self):
        self.assertEqual(self._parse([{**ROW_CAMPUS, "id": ""}, {**ROW_CAMPUS, "name": " "}]), [])


class FetchTest(unittest.TestCase):
    def _run(self, pages, url="https://xz.duoyi.com/v40/#/positions"):
        a = duoyi.DuoyiAdapter()
        calls = []

        class _Resp:
            def __init__(self, body):
                self._body = body
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._body

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get(self, url, params=None):
                calls.append(dict(params or {}))
                return _Resp(pages[len(calls) - 1])

        with mock.patch.object(duoyi.httpx, "Client", _Client):
            raw = a.fetch(url)
        return a, json.loads(raw), calls

    def test_pages_until_total_and_dedupes_sliding_window(self):
        a, doc, calls = self._run([_payload([ROW_CAMPUS], 2), _payload([ROW_CAMPUS, ROW_INTERN], 2)])
        self.assertEqual(calls[0]["recruit"], 10)
        self.assertEqual([c["pageIndex"] for c in calls], [1, 2])
        self.assertEqual(sorted(r["id"] for r in doc["rows"]), sorted([ROW_CAMPUS["id"], ROW_INTERN["id"]]))
        self.assertEqual(a.reported_total, 2)
        self.assertTrue(a.fetch_complete)

    def test_short_of_total_is_not_complete(self):
        a, doc, _ = self._run([_payload([ROW_CAMPUS], 3), _payload([], 3)])
        self.assertEqual(a.reported_total, 3)
        self.assertFalse(a.fetch_complete)

    def test_empty_board_is_a_legal_state(self):
        a, doc, _ = self._run([_payload([], 0)])
        self.assertEqual(doc["rows"], [])
        self.assertTrue(a.fetch_complete)

    def test_malformed_payload_raises_instead_of_silent_zero(self):
        with self.assertRaises(RuntimeError):
            self._run([{"message": "success", "data": {"total": 5}}])


if __name__ == "__main__":
    unittest.main()


class LivenessTest(unittest.TestCase):
    """enrich._detail_duoyi：双条件判死（message==success 且 data 键存在且为 null）。"""

    def _probe(self, status, body, jd_url="https://xz.duoyi.com/v40/#/position-detail/1674681784744284160"):
        import enrich

        class _Resp:
            status_code = status
            text = json.dumps(body, ensure_ascii=False) if body is not None else "<html>"

            def json(self):
                if body is None:
                    raise ValueError("not json")
                return body

        with mock.patch.object(enrich.httpx, "get", return_value=_Resp()):
            return enrich._detail_duoyi({"jd_url": jd_url}, {})

    def test_live_record_returns_without_error(self):
        self.assertEqual(self._probe(200, {"message": "success", "data": {"name": "游戏策划"}}), "")

    def test_success_with_null_data_is_closed(self):
        import enrich
        with self.assertRaises(enrich.JobClosedError):
            self._probe(200, {"message": "success", "data": None, "code": 0})

    def test_server_error_with_null_data_is_not_closed(self):
        import enrich
        with self.assertRaises(enrich.DetailUnknownError):
            self._probe(200, {"message": "服务端错误", "data": None, "code": 10100})

    def test_missing_data_key_or_non_json_is_unknown(self):
        import enrich
        with self.assertRaises(enrich.DetailUnknownError):
            self._probe(200, {"message": "success"})
        with self.assertRaises(enrich.DetailUnknownError):
            self._probe(200, None)

    def test_foreign_or_malformed_jd_url_makes_no_request(self):
        import enrich
        with mock.patch.object(enrich.httpx, "get", side_effect=AssertionError("must not call")):
            self.assertEqual(enrich._detail_duoyi({"jd_url": "https://example.com/#/position-detail/1"}, {}), "")
            self.assertEqual(enrich._detail_duoyi({"jd_url": "https://xz.duoyi.com/v40/positions"}, {}), "")
