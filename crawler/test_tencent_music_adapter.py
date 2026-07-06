import json
import unittest

from adapters.tencent_music import TencentMusicAdapter


class TencentMusicAdapterTest(unittest.TestCase):
    def test_parse_maps_social_and_campus_boards(self):
        payload = {
            "social": [{
                "id": "14933",
                "name": "音乐A&R经理",
                "jobf_descr": "内容类",
                "work_city": "北京",
                "date": "2026-06-15",
                "duty": "1、负责为签约艺人制定A&R定位，统筹艺人专辑/单曲的企划及制作工作。",
            }],
            "campus": [{
                "id": "14982",
                "name": "音乐大模型算法工程师",
                "job_type_descr": "应届生",
                "work_city": "深圳市",
                "duty": "1. 负责AI音乐大模型的优化研究与落地。",
            }],
        }

        jobs = TencentMusicAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 2)
        social, campus = jobs
        self.assertEqual(social.company, "腾讯音乐 TME")
        self.assertEqual(social.job_type, "社招")
        self.assertEqual(social.posted_at, "2026-06-15")
        self.assertEqual(
            social.jd_url,
            "https://join.tencentmusic.com/social/post-details/?id=14933",
        )
        self.assertEqual(campus.job_type, "应届生")
        self.assertEqual(
            campus.jd_url,
            "https://join.tencentmusic.com/campus/post-details/?id=14982",
        )

    def test_parse_drops_rows_without_id_or_title_and_dedups(self):
        payload = {
            "social": [
                {"id": "", "name": "无ID岗"},
                {"id": "1", "name": ""},
                {"id": "2", "name": "重复岗", "work_city": "北京"},
                {"id": "2", "name": "重复岗", "work_city": "北京"},
            ],
            "campus": [],
        }

        jobs = TencentMusicAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "重复岗")

    def test_parse_relative_date_returns_none(self):
        payload = {"social": [{"id": "3", "name": "岗", "date": "一周前"}], "campus": []}

        jobs = TencentMusicAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertIsNone(jobs[0].posted_at)


if __name__ == "__main__":
    unittest.main()
