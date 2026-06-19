import json
import unittest

from adapters.vivo import VivoAdapter


class VivoAdapterTest(unittest.TestCase):
    def test_parse_maps_job_ids_to_verified_detail_url(self):
        payload = {
            "data": [{
                "job_id": "M1815270404823314433",
                "job_code": "M1898Q",
                "job_title": "3D算法专家",
                "job_location_list": [{"city": "杭州"}],
                "job_category_id": "M1718986166464483330",
                "job_category": "研发类",
                "job_desc": "负责移动终端空间感知技术。",
            }]
        }

        jobs = VivoAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "vivo")
        self.assertEqual(jobs[0].title, "3D算法专家（M1898Q）")
        self.assertEqual(
            jobs[0].jd_url,
            "https://hr.vivo.com/job-detail"
            "?_irjc=M1718986166464483330"
            "&_irjid=M1815270404823314433&_collect=false",
        )


if __name__ == "__main__":
    unittest.main()
