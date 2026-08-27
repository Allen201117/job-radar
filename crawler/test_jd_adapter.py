import json
import unittest

from adapters.jd import JdAdapter
from normalizer import validate_job_quality


class JdAdapterTest(unittest.TestCase):
    def test_parses_public_job_list_rows_with_official_detail_urls(self):
        payload = [
            {
                "requirementId": 217525,
                "positionId": 217451,
                "positionNameOpen": "数据分析师",
                "jobType": "研发类",
                "workCity": "北京市",
                "formatPublishTime": "2026-05-13",
                "workContent": "负责业务数据分析。",
                "qualification": "熟练使用 SQL。",
            }
        ]

        jobs = JdAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        # 行里没有 positionDeptName（或部门不在 _DEPT_TO_COMPANY 映射表里）→ company 留空，
        # 由 normalizer 回落 sources.company（「京东」）。按部门派生子公司见 test_jd_subsidiary.py。
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].title, "数据分析师")
        self.assertEqual(jobs[0].location, "北京市")
        self.assertEqual(jobs[0].job_type, "社招")  # 只抓社招门户，job_type 固定社招（非接口职能分类）
        self.assertEqual(
            jobs[0].jd_url,
            "https://zhaopin.jd.com/web/job-info-detail?requementId=217525",
        )
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)
        self.assertIn("熟练使用 SQL", jobs[0].summary)

        is_valid, reason = validate_job_quality(
            jobs[0],
            "https://zhaopin.jd.com/web/job/job_info_list/3",
        )
        self.assertTrue(is_valid, reason)


if __name__ == "__main__":
    unittest.main()
