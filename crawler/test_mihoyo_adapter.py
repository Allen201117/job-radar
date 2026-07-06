import json
import unittest

from adapters.mihoyo import MihoyoAdapter


class MihoyoAdapterTest(unittest.TestCase):
    def test_parse_routes_social_and_campus_detail_urls(self):
        payload = {
            "list": [
                {
                    "id": "7664",
                    "title": "技术美术负责人-3D风格化MOBA预研",
                    "_board": "social",
                    "projectName": "社会招聘",
                    "jobNature": "全职",
                    "addressDetailList": [{"addressId": "8", "addressDetail": "上海"}],
                    "_info": {
                        "description": "1、制定 Lighting、材质、后处理方案。",
                        "jobRequire": "1、4 年以上技术美术经验。",
                    },
                },
                {
                    "id": "8957",
                    "title": "【提前批-大模型】LLM Evaluation算法研究员",
                    "_board": "campus",
                    "projectName": "2027届秋招",
                    "jobNature": "全职",
                    "addressDetailList": [{"addressId": "13", "addressDetail": "北京"}],
                    "jobSummary": "面向代码智能体能力构建评测体系。",
                },
            ]
        }

        jobs = MihoyoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 2)
        social, campus = jobs
        self.assertEqual(social.company, "米哈游 miHoYo")
        self.assertEqual(social.job_type, "社招")
        self.assertEqual(social.jd_url, "https://jobs.mihoyo.com/#/position/7664")
        self.assertIn("【任职要求】", social.summary)
        self.assertEqual(campus.job_type, "校招")
        self.assertEqual(campus.jd_url, "https://jobs.mihoyo.com/#/campus/position/8957")
        self.assertEqual(campus.summary, "面向代码智能体能力构建评测体系。")

    def test_intern_nature_maps_to_shixi(self):
        payload = {
            "list": [{
                "id": "9001",
                "title": "游戏运营",
                "_board": "campus",
                "projectName": "实习生专项",
                "jobNature": "全职",
                "addressDetailList": [{"addressDetail": "上海"}],
            }]
        }

        jobs = MihoyoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(jobs[0].job_type, "实习")

    def test_parse_drops_incomplete_rows_and_dedups(self):
        payload = {
            "list": [
                {"id": "", "title": "无ID"},
                {"id": "5", "title": ""},
                {"id": "6", "title": "重复", "_board": "social"},
                {"id": "6", "title": "重复", "_board": "social"},
            ]
        }

        jobs = MihoyoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)


if __name__ == "__main__":
    unittest.main()
