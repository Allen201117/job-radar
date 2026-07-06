import json
import unittest

from adapters.antgroup import AntGroupAdapter


class AntGroupAdapterTest(unittest.TestCase):
    def test_parse_maps_social_and_campus_boards(self):
        payload = {
            "social": [{
                "id": 260706010768076,
                "name": "蚂蚁集团-还款用户运营专家-杭州",
                "workLocations": ["杭州"],
                "publishTime": "2026-07-06T10:02:21.000+00:00",
                "description": "1、负责消费金融还款链路降本业务。",
                "requirement": "1、熟悉用户运营和产品运营。",
                "experience": {"from": 3, "to": None},
            }],
            "campus": [{
                "id": "25062405364658",
                "name": "【Plan A】具身智能算法工程师-灵波（实习）",
                "workLocations": ["北京", "上海", "杭州"],
                "description": "1. 核心模型研发。",
                "requirement": "1. 计算机相关专业硕士及以上。",
            }],
        }

        jobs = AntGroupAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 2)
        social, campus = jobs
        self.assertEqual(social.company, "蚂蚁集团")
        self.assertEqual(social.job_type, "社招")
        self.assertEqual(social.posted_at, "2026-07-06")
        self.assertEqual(social.experience, "3年以上")
        self.assertIn("【任职要求】", social.summary)
        self.assertEqual(
            social.jd_url,
            "https://talent.antgroup.com/off-campus-position?positionId=260706010768076",
        )
        self.assertEqual(campus.job_type, "实习")
        self.assertEqual(campus.location, "北京、上海、杭州")
        self.assertEqual(
            campus.jd_url,
            "https://talent.antgroup.com/campus-position?positionId=25062405364658",
        )

    def test_campus_without_intern_marker_is_xiaozhao(self):
        payload = {
            "social": [],
            "campus": [{"id": "1", "name": "2027届秋招-Java研发工程师", "workLocations": ["杭州"]}],
        }

        jobs = AntGroupAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(jobs[0].job_type, "校招")

    def test_parse_drops_incomplete_rows(self):
        payload = {"social": [{"id": "", "name": "无ID"}, {"id": "9", "name": ""}], "campus": []}

        jobs = AntGroupAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
