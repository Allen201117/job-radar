import json
import unittest

from adapters.bilibili import BilibiliAdapter


class BilibiliAdapterTest(unittest.TestCase):
    def test_parse_maps_social_position_to_detail_url(self):
        payload = {
            "data": {
                "list": [{
                    "id": 26613,
                    "positionName": "资深生态治理运营（国际化）",
                    "positionDescription": "工作职责：治理国际化内容。",
                    "positionTypeName": "全职",
                    "postCodeName": "运营保障类",
                    "pushTime": "2026-06-18 15:22:24",
                    "workLocation": "上海",
                }]
            }
        }

        jobs = BilibiliAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "哔哩哔哩")
        self.assertEqual(jobs[0].posted_at, "2026-06-18")
        self.assertEqual(
            jobs[0].jd_url,
            "https://jobs.bilibili.com/social/positions/26613",
        )


if __name__ == "__main__":
    unittest.main()
