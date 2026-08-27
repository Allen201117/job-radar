import json
import unittest

import normalizer
from adapters.cmbc import CmbcAdapter


class CmbcAdapterTest(unittest.TestCase):
    def test_parse_keeps_hash_detail_route_and_quality_gate_accepts_it(self):
        payload = {"jobs": [{
            "id": "job-1", "careerRecruitment_career_name": "财富经理",
            "careerRecruitment_regions_name": "大连",
            "careerRecruitment_career_publishDate": "2026-08-18 16:32:46",
            "careerRecruitment_career_expirationDate": "2026-09-15",
            "_detail": {
                "careerRecruitment_career_careerDetail_content": "<p>维护客户关系</p>",
                "careerRecruitment_career_careerDetail_qualifications": "<p>本科及以上</p>",
            },
        }]}

        jobs = CmbcAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].summary, "【岗位职责】\n维护客户关系\n【任职要求】\n本科及以上")
        self.assertEqual(jobs[0].jd_url, "https://career.cmbc.com.cn/#/app/recruitmentview/job-1")
        self.assertEqual(
            normalizer.validate_job_quality(jobs[0], "https://career.cmbc.com.cn/#/app/recruitmentlist"),
            (True, ""),
        )


if __name__ == "__main__":
    unittest.main()
