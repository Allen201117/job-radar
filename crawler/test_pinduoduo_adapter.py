import json
import unittest

from adapters.pinduoduo import PinduoduoAdapter, _has_more_pages


class PinduoduoAdapterTest(unittest.TestCase):
    def test_parse_maps_campus_position_to_detail_url(self):
        payload = {
            "result": {
                "list": [{
                    "id": "5e4eb6f3-294f-491b-9d39-42895eed98c3",
                    "name": "AI Infra研发工程师【2027届云弧计划】",
                    "workLocationName": "上海",
                    "jobName": "技术",
                    "releaseTime": 1778210700000,
                    "jobDuty": "参与大模型训练基础设施研发。",
                    "serveRequirement": "计算机相关专业优先。",
                }, {
                    "id": "hebei-job",
                    "name": "区域业务管培生",
                    "workLocationName": "河北雄安新区",
                    "jobName": "区域业务",
                    "jobDuty": "负责区域业务。",
                }, {
                    "id": "taiwan-job",
                    "name": "台湾岗位",
                    "workLocationName": "台北",
                    "jobName": "运营",
                }]
            }
        }

        jobs = PinduoduoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].company, "拼多多")
        self.assertIn("计算机相关专业", jobs[0].summary)
        self.assertEqual(
            jobs[0].jd_url,
            "https://careers.pddglobalhr.com/campus/grad/detail"
            "?positionId=5e4eb6f3-294f-491b-9d39-42895eed98c3",
        )
        self.assertEqual(jobs[1].location, "河北雄安新区")

    def test_pagination_uses_server_total_not_requested_page_size(self):
        self.assertTrue(_has_more_pages(total="27", collected=10))
        self.assertFalse(_has_more_pages(total="27", collected=27))


if __name__ == "__main__":
    unittest.main()
