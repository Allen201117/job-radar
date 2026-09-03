"""腾讯校招 / 海康校招 adapter 的 parse 单测（不打真实网络，喂假响应）。

这两家是 2027 届秋招补齐必投清单校招供给时接入的。它们各自踩到一个「参数被静默忽略」
的坑（腾讯分页参数名、海康分页参数位置），坑本身写在 adapter 注释里；这里钉死的是
**parse 的产出契约**：没有稳定 jd_url 的岗位一条都不许放出去。
"""
import json
import unittest

from adapters.hikvision import HikvisionAdapter
from adapters.tencent_campus import TencentCampusAdapter


class TencentCampusParseTest(unittest.TestCase):
    def _raw(self, rows):
        return json.dumps({"positionList": rows}, ensure_ascii=False)

    def test_正常解析并用_pid_id_拼详情页(self):
        jobs = TencentCampusAdapter().parse(self._raw([{
            "projectId": 1, "position": 783, "positionTitle": "AI全栈工程师",
            "postId": "1282707398326592512", "bgs": "CDG CSIG ",
            "workCities": "深圳总部 北京 上海 ", "recruitLabelName": "应届毕业生",
            "_desc": "1、负责产品业务系统的全栈开发。",
        }]))
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.title, "AI全栈工程师")
        self.assertEqual(j.company, "腾讯")
        # ⚠️ 必须是 pid+id，不是 postId：postId 拼出来的 jobdesc.html 实测返回「404 | 腾讯校招」，
        # 且同一岗位跨批次会换 postId，而 pid+id 稳定。
        self.assertEqual(j.jd_url, "https://join.qq.com/post_detail.html?pid=1&id=783")
        self.assertNotIn("postId", j.jd_url)
        self.assertEqual(j.location, "深圳总部", "多地点串取首个作主地点")
        self.assertIn("深圳总部 北京 上海", j.summary, "完整多地点串要留在正文里，别丢")
        self.assertIn("CDG CSIG", j.summary)
        self.assertIn("全栈开发", j.summary)
        self.assertEqual(j.job_type, "应届毕业生", "校招信号要带出来供三桶分类用")

    def test_缺_pid_或_position_的整条丢弃_绝不入库半截链接(self):
        rows = [
            {"projectId": None, "position": 783, "positionTitle": "缺 pid"},
            {"projectId": 1, "position": None, "positionTitle": "缺 position"},
            {"projectId": 1, "position": 784, "positionTitle": ""},
            {"projectId": 1, "position": 785, "positionTitle": "正常岗"},
        ]
        jobs = TencentCampusAdapter().parse(self._raw(rows))
        self.assertEqual([j.title for j in jobs], ["正常岗"])

    def test_没有正文时也能出卡_正文交给富化链路(self):
        jobs = TencentCampusAdapter().parse(self._raw([
            {"projectId": 1, "position": 900, "positionTitle": "无正文岗", "workCities": "北京 "},
        ]))
        self.assertEqual(len(jobs), 1)
        self.assertIn("北京", jobs[0].summary)

    def test_脏输入不炸(self):
        a = TencentCampusAdapter()
        self.assertEqual(a.parse("not json"), [])
        self.assertEqual(a.parse(json.dumps({})), [])
        self.assertEqual(a.parse(json.dumps({"positionList": []})), [])


class HikvisionParseTest(unittest.TestCase):
    def _raw(self, rows):
        return json.dumps({"list": rows}, ensure_ascii=False)

    def test_正常解析并带上_batchId(self):
        jobs = HikvisionAdapter().parse(self._raw([{
            "id": "7eda4cae025f41f1a2bb04c9958bc3df", "postAdName": "AI加速算法工程师",
            "batchId": "e198653730e14820b9e95b29fbc2223f", "batchName": "【2027校园招聘】",
            "jobNature": "校招应届生", "workPlace": "杭州市", "adNeedDept": "研究院",
            "postDuty": "负责算法加速。", "postRequire": "硕士及以上。",
        }]))
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.company, "海康威视")
        self.assertEqual(
            j.jd_url,
            "https://campushr.hikvision.com/JobDetails.html"
            "?id=7eda4cae025f41f1a2bb04c9958bc3df&type=2&batchId=e198653730e14820b9e95b29fbc2223f",
        )
        self.assertEqual(j.job_type, "校招应届生")
        self.assertIn("2027校园招聘", j.summary)
        self.assertIn("负责算法加速", j.summary)
        self.assertIn("硕士及以上", j.summary)

    def test_缺_batchId_的整条丢弃(self):
        # batchId 是详情页的必需参数，缺了链接就打不开 —— 宁可少一条，不入库打不开的岗。
        rows = [
            {"id": "a1", "postAdName": "无 batchId", "jobNature": "校招应届生"},
            {"id": "", "postAdName": "无 id", "batchId": "b1"},
            {"id": "a2", "postAdName": "", "batchId": "b2"},
            {"id": "a3", "postAdName": "正常岗", "batchId": "b3"},
        ]
        jobs = HikvisionAdapter().parse(self._raw(rows))
        self.assertEqual([j.title for j in jobs], ["正常岗"])

    def test_标题字段是_postAdName_不是_positionName(self):
        jobs = HikvisionAdapter().parse(self._raw([
            {"id": "a1", "postAdName": "对的标题", "positionName": "错的标题", "batchId": "b1"},
        ]))
        self.assertEqual(jobs[0].title, "对的标题")

    def test_脏输入不炸(self):
        a = HikvisionAdapter()
        self.assertEqual(a.parse("not json"), [])
        self.assertEqual(a.parse(json.dumps({"list": []})), [])


class AdapterWiringTest(unittest.TestCase):
    """接线自检：新 adapter 必须在 run.py 的 ADAPTERS 里注册，否则次日爬虫找不到它。"""

    def test_两个新_adapter_都已注册(self):
        import run
        self.assertIn("tencent_campus", run.ADAPTERS)
        self.assertIn("hikvision", run.ADAPTERS)
        self.assertIsInstance(run.ADAPTERS["tencent_campus"], TencentCampusAdapter)
        self.assertIsInstance(run.ADAPTERS["hikvision"], HikvisionAdapter)

    def test_两者都声明为_httpx_安全档(self):
        # 都是纯 httpx（无浏览器）→ 必须进 _HTTPX_SAFE_ADAPTERS，否则会被排进慢的浏览器车道。
        import run
        self.assertIn("tencent_campus", run._HTTPX_SAFE_ADAPTERS)
        self.assertIn("hikvision", run._HTTPX_SAFE_ADAPTERS)


if __name__ == "__main__":
    unittest.main()
