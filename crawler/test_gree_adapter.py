import json
import unittest

from adapters.gree import GreeAdapter


class GreeAdapterTest(unittest.TestCase):
    def test_parse_maps_property_and_uses_code_detail_url(self):
        payload = {"jobs": [
            {
                "Code": "school-1", "Position": "博士生（芯片）", "_property": 1,
                "Category": "博士生", "Location": "珠海市", "Experience": "应届毕业生",
                "Education": "博士研究生", "PubTime": "2026-08-26",
                "Description": "研究芯片设计", "Qualifications": "掌握相关专业知识",
            },
            {
                "Code": "social-1", "Position": "电商运营", "_property": 2,
                "Category": "社会招聘", "Location": "珠海市",
            },
        ]}

        jobs = GreeAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].job_type, "校招")
        self.assertEqual(jobs[0].summary, "【岗位职责】\n研究芯片设计\n【任职要求】\n掌握相关专业知识")
        self.assertEqual(jobs[0].jd_url, "https://zhaopin.greeyun.com/job?JobCode=school-1&recruitType=1")
        self.assertEqual(jobs[1].job_type, "社招")
        self.assertEqual(jobs[1].jd_url, "https://zhaopin.greeyun.com/job?JobCode=social-1&recruitType=2")


if __name__ == "__main__":
    unittest.main()
