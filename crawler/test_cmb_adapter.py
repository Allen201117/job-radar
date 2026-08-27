import json
import unittest

from adapters.cmb import CmbAdapter


class CmbAdapterTest(unittest.TestCase):
    def test_parse_uses_publish_id_and_detail_summary(self):
        payload = {"jobs": [{
            "publishGID": "publish-1", "jobDisplay": "客户经理",
            "locationName": "重庆市", "expiredOn": "2026-12-31",
            "_detail": {
                "jobResponsibility": "<p>维护客户</p>",
                "jobRequirement": "<p>本科及以上</p>",
            },
        }]}

        jobs = CmbAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].summary, "【岗位职责】\n维护客户\n【任职要求】\n本科及以上")
        self.assertEqual(jobs[0].deadline, "2026-12-31")
        self.assertEqual(
            jobs[0].jd_url,
            "https://career.cmbchina.com/positionDetail/social?publishId=publish-1",
        )


if __name__ == "__main__":
    unittest.main()
