import json
import unittest

from adapters.midea import MideaAdapter


class MideaAdapterTest(unittest.TestCase):
    def test_parse_keeps_list_jd_and_position_id_detail_url(self):
        payload = {"jobs": [{
            "positionId": "position-1", "demandPositionName": "供应链专员",
            "workingPlace": "广东省-佛山", "minWorking": "3", "maxWorking": "5",
            "education": "本科及以上", "postDuties": "负责供应链协同",
            "qualification": "具备沟通能力",
        }]}

        jobs = MideaAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "")
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].experience, "3-5年")
        self.assertEqual(jobs[0].summary, "【岗位职责】\n负责供应链协同\n【任职要求】\n具备沟通能力")
        self.assertEqual(
            jobs[0].jd_url,
            "https://recruit.midea.com/recruitOut/ihr/social/jobApplication?positionId=position-1&recruitType=social",
        )


if __name__ == "__main__":
    unittest.main()
