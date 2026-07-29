import unittest

from adapters.baidu import BaiduAdapter


class BaiduAdapterTest(unittest.TestCase):
    def test_parses_initial_data_with_official_detail_urls(self):
        html = """
        <script>
        window.__INITIAL_DATA__ ={"listData":{"recruitType":"SOCIAL","listDetailData":[
          {"postId":"46ad568d-c116-417c-91fa-49146c36bb05","name":"DuMate后端研发（J99773）","workPlace":"北京市","postType":"技术","updateDate":"2026-05-20","workContent":"负责后端研发","serviceCondition":"熟悉 Go","projectType":undefined}
        ]}}; window.prefix="/jobs";undefined
        </script>
        """

        jobs = BaiduAdapter().parse(html)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].company, "百度")
        self.assertEqual(jobs[0].title, "DuMate后端研发（J99773）")
        self.assertEqual(jobs[0].location, "北京市")
        # recruitType=SOCIAL → 招聘类型"社招"（而非把岗位类别"技术"误当 job_type）
        self.assertEqual(jobs[0].job_type, "社招")
        self.assertEqual(jobs[0].summary, "负责后端研发")
        self.assertEqual(jobs[0].posted_at, "2026-05-20")
        self.assertEqual(
            jobs[0].jd_url,
            "https://talent.baidu.com/jobs/detail/SOCIAL/46ad568d-c116-417c-91fa-49146c36bb05",
        )

    def test_recruit_type_maps_campus_and_intern(self):
        html = """
        <script>
        window.__INITIAL_DATA__ ={"listData":{"recruitType":"CAMPUS","listDetailData":[
          {"postId":"c1","name":"2026校招-算法工程师","workPlace":"北京市","postType":"技术","workContent":"算法研发"},
          {"postId":"i1","name":"数据分析实习","workPlace":"上海市","postType":"技术","workContent":"数据分析","recruitType":"INTERN"}
        ]}}; window.prefix="/jobs";
        </script>
        """

        jobs = BaiduAdapter().parse(html)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].job_type, "校招")  # 列表级 recruitType=CAMPUS
        self.assertEqual(jobs[1].job_type, "实习")  # 行级 recruitType=INTERN 覆盖


if __name__ == "__main__":
    unittest.main()


class BaiduPaginationTest(unittest.TestCase):
    """回归守卫：百度必须翻全，不能只拿首页。

    2026-07-28 实测：旧实现只 GET 一次 SSR 列表页，__INITIAL_DATA__ 里只有首页 10 条，
    而接口自报社招 1571 + 实习 415 → 每轮只抓到 0.6%，库里 41 个存量岗几乎永不刷新。
    真正的翻页在 form-encoded POST /httservice/getPostListNew 上（JSON body 会被拒；
    pageSize 被服务端锁死 10，传大值返回 0 条）。live 验证改后 10 → 1986 岗、fetch_complete=True。
    """

    def _fake_client(self, totals):
        """按 recruitType 造分页响应；记录每次请求，用来断言真的翻了页、且用的是 form 编码。"""
        calls = []

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeClient:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def post(self_inner, url, data=None, **_kw):
                calls.append((url, dict(data or {})))
                rt = (data or {}).get("recruitType")
                page = int((data or {}).get("curPage", 1))
                size = int((data or {}).get("pageSize", 10))
                total = totals.get(rt, 0)
                start = (page - 1) * size
                rows = [{"postId": f"{rt}-{i}", "name": f"{rt} 岗位 {i}"}
                        for i in range(start, min(start + size, total))]
                return FakeResp({"data": {"list": rows, "total": total}})

        return FakeClient, calls

    def test_fetches_every_page_not_just_the_first(self):
        FakeClient, calls = self._fake_client({"SOCIAL": 25, "CAMPUS": 0, "INTERN": 12})
        adapter = BaiduAdapter()
        import adapters.baidu as mod
        orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: FakeClient()
        try:
            jobs = adapter.parse(adapter.fetch("https://talent.baidu.com/jobs/social-list"))
        finally:
            mod.httpx.Client = orig

        self.assertEqual(len(jobs), 37, "25 社招 + 12 实习 必须全部抓到，不能只有首页 10 条")
        self.assertEqual(adapter.reported_total, 37)
        self.assertTrue(adapter.fetch_complete)
        self.assertTrue(all(c[1].get("pageSize") == 10 for c in calls),
                        "pageSize 被服务端锁死 10，传别的值会返回 0 条")
        social_pages = sorted(int(c[1]["curPage"]) for c in calls if c[1]["recruitType"] == "SOCIAL")
        self.assertEqual(social_pages[:3], [1, 2, 3], f"社招没有逐页翻，实际请求页码 {social_pages}")

    def test_detail_url_uses_requested_recruit_type(self):
        """列表行自己不带 recruitType，但详情 URL 要用它 → 必须按本次请求的类型盖上，否则拼出坏链。"""
        FakeClient, _ = self._fake_client({"SOCIAL": 0, "CAMPUS": 0, "INTERN": 3})
        adapter = BaiduAdapter()
        import adapters.baidu as mod
        orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: FakeClient()
        try:
            jobs = adapter.parse(adapter.fetch("https://talent.baidu.com/jobs/social-list"))
        finally:
            mod.httpx.Client = orig

        self.assertEqual(len(jobs), 3)
        self.assertTrue(all("/jobs/detail/INTERN/" in j.jd_url for j in jobs),
                        [j.jd_url for j in jobs])
        self.assertTrue(all(j.job_type == "实习" for j in jobs))
