import unittest

from adapters.alibaba import AlibabaAdapter, AlibabaCampusAdapter


def _row(**over):
    row = {
        "id": 199902900003,
        "name": "算法工程师-AIGC方向",
        "_host": "talent.taotian.com",
        "description": "岗位描述",
        "requirement": "任职要求",
        "workLocations": ["杭州"],
        "categoryType": "freshman",
        "batchName": "淘天集团2026届秋季应届生招聘",
    }
    row.update(over)
    return row


class TestAlibabaBoardRouting(unittest.TestCase):
    def test_campus_adapter_uses_campus_portal_in_jd_url(self):
        a = AlibabaCampusAdapter(); a.company_name = "淘天集团"
        job = a._map(_row())
        self.assertIn("/campus/position-detail", job.jd_url)
        self.assertNotIn("off-campus", job.jd_url)

    def test_social_adapter_keeps_off_campus_portal(self):
        # 参数化不能改动社招原行为：13 个 BU 的社招详情页 URL 已 live 验证过，不许漂移
        s = AlibabaAdapter(); s.company_name = "淘天集团"
        job = s._map(_row())
        self.assertIn("/off-campus/position-detail", job.jd_url)
        self.assertEqual(job.job_type, "社会招聘")

    def test_campus_job_type_carries_batch_name_for_grad_class(self):
        # 批次名带届别（「2026届秋季应届生招聘」），比标题更可靠 → 喂给 normalizer 抽 grad_class
        a = AlibabaCampusAdapter(); a.company_name = "淘天集团"
        job = a._map(_row())
        self.assertIn("2026届", job.job_type)
        from grad_class import extract_grad_class
        self.assertEqual(extract_grad_class(job.title, job.job_type, job.summary), 2026)


class TestAlibabaCampusPayloadSelfProof(unittest.TestCase):
    """⚠️ 核心防线：校招频道靠「不传 channel」拿到，那是服务端 fallback 行为不是契约。

    若哪天默认集变成社招，只信入参就会把几千个社招岗当校招灌进校招专区——用户按校招投了
    社招岗，比漏抓更糟。所以必须用 payload 自证，自证不过宁可抓 0 条。
    """

    def setUp(self):
        self.a = AlibabaCampusAdapter(); self.a.company_name = "淘天集团"

    def test_accepts_freshman_category(self):
        self.assertIsNotNone(self.a._map(_row(categoryType="freshman", batchName="")))

    def test_accepts_batch_name_with_jie(self):
        self.assertIsNotNone(self.a._map(_row(categoryType="", batchName="2027届秋季应届生招聘")))

    def test_rejects_row_without_any_campus_proof(self):
        # 社招行：categoryType 非 freshman、batchName 空 → 丢弃
        self.assertIsNone(self.a._map(_row(categoryType="social", batchName="")))
        self.assertIsNone(self.a._map(_row(categoryType=None, batchName=None)))

    def test_rejects_batch_name_without_jie(self):
        # 有批次名但不含「届」（如社招专场）→ 不足以自证校招
        self.assertIsNone(self.a._map(_row(categoryType="experienced", batchName="2026 社招专场")))

    def test_case_insensitive_category_type(self):
        self.assertIsNotNone(self.a._map(_row(categoryType="FreshMan", batchName="")))


class TestEmptyVsBroken(unittest.TestCase):
    """「一条岗都没有」有两种成因，处置完全相反——不区分就会把「2027 届还没开闸」
    天天记成抓取失败，把真故障淹在噪音里（2026-08-04 首轮车道实测踩到：3 个阿里校招源
    全部 FAILED，其实只是那几个 BU 的校招频道还没放岗）。"""

    def _adapter_with_fake_client(self, responses):
        """responses: 依次返回的 (status_code, json) 或 Exception。"""
        import httpx
        from adapters import alibaba

        class FakeResp:
            def __init__(self, payload): self._p = payload
            def raise_for_status(self): pass
            def json(self): return self._p

        class FakeClient:
            def __init__(self, *a, **k): self.cookies = {"XSRF-TOKEN": "t"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def get(self, *a, **k): return FakeResp({})
            def post(self, *a, **k):
                item = responses.pop(0) if responses else {"content": {"datas": [], "totalCount": 0}}
                if isinstance(item, Exception):
                    raise item
                return FakeResp(item)

        return FakeClient, alibaba, httpx

    def test_api_answered_with_zero_jobs_does_not_raise(self):
        FakeClient, alibaba, _ = self._adapter_with_fake_client(
            [{"content": {"datas": [], "totalCount": 0}}])
        orig = alibaba.httpx.Client
        alibaba.httpx.Client = FakeClient
        try:
            a = alibaba.AlibabaCampusAdapter(); a.company_name = "阿里云"
            raw = a.fetch("https://careers.aliyun.com/campus/position-list?lang=zh")
            self.assertEqual(a.parse(raw), [])
            self.assertEqual(a.reported_total, 0)
            self.assertTrue(a.fetch_complete)   # 0/0 = 抓全了，不是没抓完
        finally:
            alibaba.httpx.Client = orig

    def test_api_never_answered_raises(self):
        import httpx as _h
        FakeClient, alibaba, _ = self._adapter_with_fake_client([_h.ConnectError("boom")])
        orig = alibaba.httpx.Client
        alibaba.httpx.Client = FakeClient
        try:
            a = alibaba.AlibabaCampusAdapter(); a.company_name = "X"
            with self.assertRaises(RuntimeError):
                a.fetch("https://x.alibaba.com/campus/position-list?lang=zh")
        finally:
            alibaba.httpx.Client = orig


if __name__ == "__main__":
    unittest.main()
