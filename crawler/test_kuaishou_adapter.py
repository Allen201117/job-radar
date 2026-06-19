import json
import unittest

from adapters.kuaishou import KuaishouAdapter


class KuaishouAdapterTest(unittest.TestCase):
    def test_parse_maps_signed_browser_response_to_detail_url(self):
        payload = {
            "_intercepted": [{
                "code": 0,
                "result": {
                    "list": [{
                        "id": 31254,
                        "name": "AI Agent 全栈工程师（音视频方向）",
                        "recruitProjectCode": "socialr",
                        "positionCategoryCode": "J0011",
                        "workExperienceCode": "4",
                        "workLocationsCode": ["Beijing", "Shanghai", "Shenzhen"],
                        "description": "负责设计和开发 AI Agent。",
                        "positionDemand": "本科及以上学历。",
                        "updateTime": "2026-06-18T20:18:08.000+08:00",
                    }]
                },
            }]
        }

        jobs = KuaishouAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "快手")
        self.assertEqual(jobs[0].location, "北京、上海、深圳")
        self.assertIn("本科及以上", jobs[0].summary)
        self.assertEqual(
            jobs[0].jd_url,
            "https://zhaopin.kuaishou.cn/#/official/social/job-info/31254",
        )


if __name__ == "__main__":
    unittest.main()
