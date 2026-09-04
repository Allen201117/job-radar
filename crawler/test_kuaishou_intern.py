"""快手 adapter：社招 + 日常实习双渠道映射。

背景：`campus.kuaishou.cn`（校园招聘 tab 跳转的域名）robots 全站禁止 → 快手校招不抓，这是红线。
但**日常实习**在 `zhaopin.kuaishou.cn` 上（无 robots 限制），与社招同接口同签名，
只差一个 positionNatureCode。此前只配了社招 URL，1,087 个实习岗白漏。

钉死两件事：① 类型/详情链按岗位行自带的 positionNatureCode 逐条判，不按来源 URL 猜；
② campus.kuaishou.cn 永远不许出现在 list_urls 里。
"""
import unittest

from adapters.kuaishou import KuaishouAdapter


def _post(nature, job_id=32501, name="热点大事件运营实习生"):
    return {
        "id": job_id, "name": name,
        "positionNatureCode": nature,
        "workLocationsCode": ["Beijing"],
        "description": "负责热点内容运营" * 6,
        "positionDemand": "在校生优先",
    }


class KuaishouNatureTest(unittest.TestCase):
    def setUp(self):
        self.adapter = KuaishouAdapter()
        self.adapter.regions = ["CN"]

    def test_intern_post_maps_to_intern_type_and_route(self):
        job = self.adapter._map(_post("C002"))
        self.assertEqual(job.job_type, "实习")
        self.assertEqual(job.jd_url,
                         "https://zhaopin.kuaishou.cn/#/official/trainee/job-info/32501")

    def test_social_post_keeps_existing_type_and_route(self):
        """存量 1,700+ 条社招岗的 jd_url 不能变——变了会按新 canonical 重新入库成重复。"""
        job = self.adapter._map(_post("C001", job_id=32377, name="激励策略产品经理"))
        self.assertEqual(job.job_type, "社会招聘")
        self.assertEqual(job.jd_url,
                         "https://zhaopin.kuaishou.cn/#/official/social/job-info/32377")

    def test_unknown_nature_falls_back_to_social(self):
        job = self.adapter._map(_post("C999"))
        self.assertEqual(job.job_type, "社会招聘")
        self.assertIn("/official/social/job-info/", job.jd_url)

    def test_missing_nature_does_not_crash(self):
        post = _post("C002")
        post.pop("positionNatureCode")
        self.assertIsNotNone(self.adapter._map(post))

    def test_campus_domain_never_listed(self):
        """campus.kuaishou.cn robots = Disallow: / —— 加进 list_urls 就是踩合规红线。"""
        for url in KuaishouAdapter.list_urls:
            self.assertNotIn("campus.kuaishou.cn", url)

    def test_intern_channel_is_configured(self):
        self.assertTrue(any("trainee" in u for u in KuaishouAdapter.list_urls),
                        "日常实习渠道必须在 list_urls 里，否则 1,087 个实习岗抓不到")


if __name__ == "__main__":
    unittest.main()
