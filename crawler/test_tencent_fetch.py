import json
import unittest
from unittest.mock import patch

from adapters.tencent import TencentAdapter


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _post(post_id, title, url=None):
    return {
        "PostId": post_id,
        "RecruitPostName": title,
        "LocationName": "深圳",
        "Responsibility": f"{title} 职责正文",
        "PostURL": url,
    }


class TencentFetchTest(unittest.TestCase):
    def test_fetches_three_attr_boards_through_reported_count(self):
        boards = {
            "1": [
                [_post("s1", "社招一", "https://careers.tencent.com/jobdesc.html?postId=s1"),
                 _post("s2", "社招二", "https://workday.example/jobs/s2")],
                [_post("s3", "社招三", "https://careers.tencent.com/jobdesc.html?postId=s3")],
            ],
            "2": [
                [_post("c1", "校招一", "https://careers.tencent.com/jobdesc.html?postId=c1")],
            ],
            "3": [
                [_post("i1", "实习一", "https://careers.tencent.com/jobdesc.html?postId=i1"),
                 _post("i2", "实习二", "https://careers.tencent.com/jobdesc.html?postId=i2")],
            ],
        }
        calls = []

        def fake_get(url, **kwargs):
            params = kwargs["params"]
            attr_id = params.get("attrId")
            page = int(params.get("pageIndex"))
            calls.append((attr_id, page, params.get("pageSize"), params.get("keyword")))
            self.assertEqual(url, TencentAdapter.API_URL)
            self.assertIn(attr_id, {"1", "2", "3"})
            self.assertEqual(params.get("language"), "zh-cn")
            rows = boards[attr_id][page - 1] if page <= len(boards[attr_id]) else []
            total = sum(len(chunk) for chunk in boards[attr_id])
            return _Response({"Data": {"Count": total, "Posts": rows}})

        adapter = TencentAdapter()
        adapter.PAGE_SIZE = 2

        with patch("adapters.tencent.httpx.get", side_effect=fake_get):
            payload = adapter.fetch("https://careers.tencent.com/search.html")

        jobs = adapter.parse(payload)
        by_title = {job.title: job for job in jobs}
        self.assertEqual([call[0] for call in calls], ["1", "1", "2", "3"])
        self.assertEqual(adapter.reported_total, 6)
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(len(jobs), 6)
        self.assertEqual(by_title["社招二"].jd_url, "https://workday.example/jobs/s2")
        self.assertEqual(by_title["社招一"].job_type, "社招")
        self.assertEqual(by_title["校招一"].job_type, "校招")
        self.assertEqual(by_title["实习一"].job_type, "实习")

    def test_uses_posturl_before_postid_fallback(self):
        payload = {
            "Data": {
                "Posts": [
                    {
                        "PostId": "fallback",
                        "RecruitPostName": "海外岗",
                        "PostURL": "https://tencent.wd1.myworkdayjobs.com/job/abc",
                        "LocationName": "新加坡",
                        "Responsibility": "负责海外业务。",
                        "_attrId": "1",
                    },
                    {
                        "PostId": "only-id",
                        "RecruitPostName": "仅有 PostId",
                        "LocationName": "深圳",
                        "Responsibility": "负责平台。",
                        "_attrId": "2",
                    },
                ]
            }
        }

        jobs = TencentAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(jobs[0].jd_url, "https://tencent.wd1.myworkdayjobs.com/job/abc")
        self.assertEqual(
            jobs[1].jd_url,
            "https://careers.tencent.com/jobdesc.html?postId=only-id",
        )
        self.assertEqual(jobs[1].job_type, "校招")


if __name__ == "__main__":
    unittest.main()
