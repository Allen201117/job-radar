import json
import unittest

from adapters.meituan import MeituanAdapter


class MeituanAdapterTest(unittest.TestCase):
    def test_parse_maps_china_job_to_verified_detail_url(self):
        payload = {
            "data": {
                "list": [{
                    "jobUnionId": "3976826625",
                    "name": "闪购-食品采销",
                    "jobFamily": "零售类",
                    "cityList": [{"name": "北京市"}, {"name": "天津市"}],
                    "jobDuty": "负责食品品类采购。",
                    "jobRequirement": "本科及以上学历。",
                    "refreshTime": 1781865904000,
                }]
            }
        }

        jobs = MeituanAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "美团")
        self.assertEqual(jobs[0].location, "北京市、天津市")
        self.assertIn("本科及以上", jobs[0].summary)
        self.assertEqual(
            jobs[0].jd_url,
            "https://zhaopin.meituan.com/web/position/detail"
            "?jobUnionId=3976826625&highlightType=social",
        )


if __name__ == "__main__":
    unittest.main()
