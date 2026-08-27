import json
import unittest

from adapters.cnstaff import CnstaffAdapter


class CnstaffAdapterTest(unittest.TestCase):
    def test_parse_unions_all_categories_and_unescapes_job_desc(self):
        payload = {
            "host": "brightdairy.cnstaff.com",
            "jobs": CnstaffAdapter._jobs_from_payload([
                {"system_job_type_cn": "社会招聘", "son": [
                    {"name": "全部", "son": [{"job_id": "4086", "job_name": "销售主管", "job_address_name": "奉贤区", "job_desc": "&lt;p&gt;岗位职责：销售&lt;/p&gt;", "job_published_at": "2026-08-27 10:00:00"}]},
                    {"name": "销售类", "son": [{"job_id": "4086", "job_name": "销售主管"}, {"job_id": "4090", "job_name": "渠道专员", "job_desc": "&lt;p&gt;任职要求：沟通&lt;/p&gt;"}]},
                ]},
                {"system_job_type_cn": "校园招聘", "son": [
                    {"name": "全部", "son": [{"job_id": "5001", "job_name": "营销培训生"}]},
                ]},
            ]),
        }
        jobs = CnstaffAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 3)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].summary, "岗位职责：销售")
        self.assertEqual(jobs[0].jd_url, "https://brightdairy.cnstaff.com/recruitment/job/detail/id/4086/")
        self.assertEqual(jobs[-1].job_type, "校招")


if __name__ == "__main__":
    unittest.main()
