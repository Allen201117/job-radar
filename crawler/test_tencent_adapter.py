import json
import unittest

from adapters.tencent import TencentAdapter
from normalizer import validate_job_quality


class TencentAdapterTest(unittest.TestCase):
    def test_parses_public_api_posts_with_official_detail_urls(self):
        payload = {
            "Data": {
                "Posts": [
                    {
                        "PostId": "1983836062820225024",
                        "RecruitPostName": "商业分析经理-广告产品方向",
                        "LocationName": "深圳",
                        "CategoryName": "产品",
                        "Responsibility": "负责广告产品的商业分析。",
                        "LastUpdateTime": "2026年05月30日",
                    }
                ]
            }
        }

        jobs = TencentAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "腾讯")
        self.assertEqual(jobs[0].title, "商业分析经理-广告产品方向")
        self.assertEqual(jobs[0].location, "深圳")
        self.assertEqual(
            jobs[0].jd_url,
            "https://careers.tencent.com/jobdesc.html?postId=1983836062820225024",
        )
        self.assertEqual(jobs[0].apply_url, jobs[0].jd_url)
        self.assertEqual(jobs[0].posted_at, "2026-05-30")
        self.assertIn("广告产品", jobs[0].summary)

        is_valid, reason = validate_job_quality(jobs[0], "https://careers.tencent.com/")
        self.assertTrue(is_valid, reason)

    def test_skips_rows_without_postid(self):
        payload = {"Data": {"Posts": [{"RecruitPostName": "无 PostId 脏数据"}]}}
        jobs = TencentAdapter().parse(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
