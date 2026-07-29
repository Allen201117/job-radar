"""国聘公开接口 fixture：离线运行，不访问网络。"""
import json
from pathlib import Path
import unittest

from adapters.iguopin import IguopinAdapter, _company_keyword


class IguopinAdapterTest(unittest.TestCase):
    def test_parse_verified_detail_job(self):
        fixture = Path(__file__).with_name("fixtures") / "iguopin_list.json"
        row = json.loads(fixture.read_text(encoding="utf-8"))["data"]["list"][0]
        row["_detail_verified"] = True
        row["_jd"] = row["contents"]  # GET /api/jobs/v1/info?id=... 的真实 data.contents

        jobs = IguopinAdapter().parse(json.dumps({"list": [row]}, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "技术总工（道路、隧道）")
        self.assertEqual(jobs[0].jd_url,
                         "https://www.iguopin.com/job/detail?id=205308503458317218")
        self.assertGreaterEqual(len(jobs[0].summary or ""), 60)
        self.assertEqual(jobs[0].deadline, "2026-09-14 23:59:59")

    def test_parse_rejects_unverified_list_item(self):
        jobs = IguopinAdapter().parse(json.dumps({"list": [{"job_id": "1", "job_name": "岗位"}]}))
        self.assertEqual(jobs, [])

    def test_source_url_company_keyword(self):
        self.assertEqual(
            _company_keyword("https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%BB%BA%E7%AD%91"),
            "中国建筑")


if __name__ == "__main__":
    unittest.main()
