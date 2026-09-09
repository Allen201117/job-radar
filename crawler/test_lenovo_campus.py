"""联想校招 adapter：字典码翻译 + 翻页收尾判定，离线 fixture 不打真实网络。"""
import json
import unittest

from adapters.lenovo import LenovoAdapter


class LenovoParseTest(unittest.TestCase):
    def test_parse_maps_city_education_and_project_type_dicts(self):
        rows = [{
            "id": 2339,
            "jobName": "数据开发工程师",
            "projectType": 1,
            "workPlace": "6,1,5",
            "educationRequired": "2",
            "typeName": "数据类",
            "jobDuties": "<p>负责数据开发。</p>",
            "jobRequirement": "<p>熟悉 SQL。</p>",
        }]

        jobs = LenovoAdapter().parse(json.dumps({"rows": rows}, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.company, "联想 Lenovo")
        self.assertEqual(job.title, "数据开发工程师")
        # 多城市取字典翻译后的第一个（天津），不是原始字典码
        self.assertEqual(job.location, "天津")
        self.assertEqual(job.job_type, "校招")  # projectType=1 → 应届生招聘
        self.assertEqual(job.education, "本科")  # educationRequired="2"
        self.assertEqual(job.jd_url, "https://talent.lenovo.com.cn/position/detail?id=2339")
        self.assertEqual(job.apply_url, job.jd_url)
        # 全部城市（翻译后）与 HTML 已去标签的职责/要求都要进 summary
        self.assertIn("招聘城市：天津、北京、深圳", job.summary)
        self.assertIn("负责数据开发。", job.summary)
        self.assertIn("熟悉 SQL。", job.summary)
        self.assertNotIn("<p>", job.summary)

    def test_project_type_3_maps_to_talent_program_campus(self):
        rows = [{
            "id": 9001,
            "jobName": "战略分析",
            "projectType": 3,
            "workPlace": "1",
            "educationRequired": "3",
            "typeName": "战略类",
            "jobDuties": "<p>参与战略项目。</p>",
            "jobRequirement": "<p>硕士以上。</p>",
        }]

        jobs = LenovoAdapter().parse(json.dumps({"rows": rows}, ensure_ascii=False))

        self.assertEqual(jobs[0].job_type, "校招（人才项目）")
        self.assertEqual(jobs[0].education, "硕士研究生")
        self.assertEqual(jobs[0].location, "北京")
        # 单城市不重复列进 summary 的「招聘城市」段
        self.assertNotIn("招聘城市：", jobs[0].summary)

    def test_missing_job_id_or_title_is_skipped(self):
        rows = [
            {"id": None, "jobName": "无 id", "workPlace": "1"},
            {"id": 1, "jobName": "", "workPlace": "1"},
        ]

        jobs = LenovoAdapter().parse(json.dumps({"rows": rows}, ensure_ascii=False))

        self.assertEqual(jobs, [])

    def test_malformed_json_returns_empty(self):
        self.assertEqual(LenovoAdapter().parse("not json"), [])


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    """按 pageNum 返回可配页数据，模拟 result.rows / result.total。"""

    def __init__(self, pages, total):
        self.pages = pages  # {page_num: [row,...]}
        self.total = total
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def get(self, url, params=None):
        page_num = params["pageNum"]
        self.calls.append(page_num)
        rows = self.pages.get(page_num, [])
        return _FakeResp({"code": 0, "message": "请求成功", "result": {"rows": rows, "total": self.total}})


def _row(i):
    return {"id": i, "jobName": f"岗位{i}", "workPlace": "1", "educationRequired": "2", "typeName": "x"}


def _run(pages, total):
    import adapters.lenovo as mod
    client = _FakeClient(pages, total)
    orig, mod.httpx.Client = mod.httpx.Client, lambda *a, **k: client
    try:
        adapter = LenovoAdapter()
        raw = adapter.fetch("https://talent.lenovo.com.cn/position")
    finally:
        mod.httpx.Client = orig
    return adapter, raw, client


class LenovoFetchCompleteTest(unittest.TestCase):
    def test_fetch_complete_when_all_pages_collected(self):
        adapter, raw, client = _run(
            pages={1: [_row(1), _row(2)], 2: [_row(3)]},
            total=3,
        )
        self.assertTrue(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 3)
        data = json.loads(raw)
        self.assertEqual(len(data["rows"]), 3)
        self.assertEqual(client.calls, [1, 2])

    def test_fetch_incomplete_when_a_page_stalls_with_no_new_ids(self):
        # 第 2 页返回全部已见过的 id（翻页失效场景）→ 必须停且 complete=False，不能误判抓全
        adapter, raw, client = _run(
            pages={1: [_row(1), _row(2)], 2: [_row(1), _row(2)]},
            total=5,
        )
        self.assertFalse(adapter.fetch_complete)
        self.assertEqual(adapter.reported_total, 5)
        data = json.loads(raw)
        self.assertEqual(len(data["rows"]), 2)


if __name__ == "__main__":
    unittest.main()
