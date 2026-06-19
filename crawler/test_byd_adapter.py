import json
import os
import unittest

import httpx

from adapters.byd import BydAdapter, _list_offsets


class _StubResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._data}


class _StubClient:
    """记录 queryDetail 调用、按 id 返回带 tagDetailList 的 detail（模拟公开接口，不打网络）。"""

    def __init__(self):
        self.calls = []

    def post(self, url, json):  # noqa: A002 (匹配 httpx.Client.post 关键字签名)
        jid = json["id"]
        self.calls.append(jid)
        return _StubResp({"id": jid, "positionName": f"岗位{jid}",
                          "tagDetailList": [{"name": "工作职责", "detail": "x"}]})


class BydAdapterTest(unittest.TestCase):
    def test_list_offsets_use_api_row_offsets_not_page_numbers(self):
        self.assertEqual(_list_offsets(total=2163, page_size=1000), [0, 1000, 2000])
        self.assertEqual(_list_offsets(total=999, page_size=1000), [0])

    def test_parse_only_emits_rows_with_browser_verified_detail_url(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?verified-token"
                ),
                "detail": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "positionTypeId": "003091",
                    "fatherOrgName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "publishTime": "2026-06-05",
                    "tagDetailList": [
                        {"name": "工作职责", "detail": "负责维修车辆顾客接待。"},
                        {"name": "任职要求", "detail": "沟通协调能力强。"},
                    ],
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "比亚迪")
        self.assertEqual(jobs[0].location, "广东省-湛江市")
        self.assertIn("沟通协调能力强", jobs[0].summary)
        self.assertIn("socialPositionDetails?", jobs[0].jd_url)

    def test_parse_keeps_batch_encrypted_list_row_without_detail_enrichment(self):
        payload = {
            "jobs": [{
                "jd_url": (
                    "https://job.byd.com/portal/pc/#/social/"
                    "socialPositionDetails?Y1KjFap0IfmxZbvDidhqr7iflfUYCzJDKePomU8QFx4="
                ),
                "row": {
                    "id": "2062698235843137537",
                    "positionName": "店端服务顾问",
                    "fatherOrgAliasName": "汽车事业群",
                    "province": "广东省",
                    "city": "湛江市",
                    "createTime": "2026-06-05 08:49:17",
                },
            }]
        }

        jobs = BydAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "店端服务顾问")
        self.assertEqual(jobs[0].job_type, "汽车事业群")
        self.assertEqual(jobs[0].posted_at, "2026-06-05")


class BydFetchDetailsTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def tearDown(self):
        os.environ.pop("CRAWL_DETAIL_CAP", None)

    def test_fetch_details_covers_all_ids_not_capped_at_20(self):
        client = _StubClient()
        ids = [str(i) for i in range(25)]  # >20：旧 DETAIL_CAP=20 只补前 20，现覆盖全量
        details = BydAdapter()._fetch_details(client, ids)
        self.assertEqual(len(details), 25)
        self.assertEqual(sorted(client.calls, key=int), sorted(ids, key=int))
        self.assertEqual(details["7"]["positionName"], "岗位7")

    def test_fetch_details_skipped_when_env_cap_zero(self):
        os.environ["CRAWL_DETAIL_CAP"] = "0"  # 快档：跳过逐岗富化
        details = BydAdapter()._fetch_details(_StubClient(), ["1", "2", "3"])
        self.assertEqual(details, {})

    def test_fetch_details_skips_failed_fetches(self):
        class _FlakyClient(_StubClient):
            def post(self, url, json):
                if json["id"] == "2":
                    raise httpx.HTTPError("boom")  # 单岗失败不阻断整批
                return super().post(url, json)

        details = BydAdapter()._fetch_details(_FlakyClient(), ["1", "2", "3"])
        self.assertEqual(set(details), {"1", "3"})


if __name__ == "__main__":
    unittest.main()
