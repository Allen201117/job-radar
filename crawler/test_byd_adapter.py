import json
import unittest

from adapters.byd import BydAdapter


class BydAdapterTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
