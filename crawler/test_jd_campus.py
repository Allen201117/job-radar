"""京东校招 adapter 的 parse 单测（不打真实网络，喂 live 实测过的真实响应形状）。

⚠️ 这里的假数据**必须照抄 live 实测的字段名**，不能用「常见猜法」：
   京东的响应是 `{"success":true,"body":{"totalNumber":N,"items":[…]}}` ——
   不是 body.list / body.records，总数键是 totalNumber 不是 total/count。
   字段猜错时 adapter 仍能跑出岗位（PlaywrightAdapter 有兜底扫描），但
   **正文全空、城市全空、reported_total 恒 None**，抓全自检彻底失效 —— 这种「跑通了其实没拿到」
   正是本项目最忌讳的静默失败，所以单测钉的是字段名本身。
"""
import json
import unittest

from adapters.jd_campus import JdCampusAdapter


def _resp(items, total=None):
    body = {"items": items}
    if total is not None:
        body["totalNumber"] = total
    return {"success": True, "body": body}


def _raw(items, total=None):
    return json.dumps({"_intercepted": [_resp(items, total)]}, ensure_ascii=False)


# live 2026-09-03 从 campus.jd.com 实际抓到的一条（截断保留结构）
REAL_ITEM = {
    "publishId": 9073,
    "reqId": 2402,
    "positionName": "市场营销",
    "positionDept": None,
    "workCity": None,           # ⚠️ 顶层恒为 None，真城市在 requirementVoList
    "publishTime": 1784814534000,
    "jobDirection": "市场与商务方向",
    "jobCategory": "营销类",
    "workContent": "1. 根据部门业务运营规划和市场节奏，结合时事热点形成营销方案。",
    "qualification": "1. 2026年10月1日至2027年9月30日期间毕业，统招本科及以上学历。",
    "requirementVoList": [
        {"workCity": "北京市-北京市", "positionBg": "京东健康", "reqId": 2402},
        {"workCity": "上海市-上海市", "positionBg": "京东零售", "reqId": 2402},
        {"workCity": "北京市-北京市", "positionBg": "京东健康", "reqId": 2402},
    ],
}


class JdCampusParseTest(unittest.TestCase):
    def test_按真实字段解析出标题_城市_正文(self):
        jobs = JdCampusAdapter().parse(_raw([REAL_ITEM], total=126))
        self.assertEqual(len(jobs), 1)
        j = jobs[0]
        self.assertEqual(j.company, "京东")
        self.assertEqual(j.title, "市场营销")
        # 城市取 requirementVoList 里第一个，且去重后的全集进正文
        self.assertEqual(j.location, "北京市-北京市")
        self.assertIn("上海市-上海市", j.summary)
        self.assertEqual(j.summary.count("北京市-北京市"), 1, "多条需求指向同一城市时要去重")
        self.assertIn("京东健康", j.summary)
        self.assertIn("京东零售", j.summary)
        self.assertIn("市场与商务方向", j.summary)
        # workContent / qualification 是列表接口直接给的全文，不该丢
        self.assertIn("结合时事热点形成营销方案", j.summary)
        self.assertIn("2027年9月30日期间毕业", j.summary)

    def test_jd_url_用_publishId_拼_details_路由(self):
        j = JdCampusAdapter().parse(_raw([REAL_ITEM]))[0]
        # ⚠️ 真实路由是 #/details?id=，其余（#/jobDetail、#/job、#/positionDetail）实测全渲染空白页
        self.assertEqual(j.jd_url, "https://campus.jd.com/#/details?id=9073")
        self.assertEqual(j.apply_url, j.jd_url)

    def test_缺_publishId_或标题的整条丢弃(self):
        items = [
            {**REAL_ITEM, "publishId": None},
            {**REAL_ITEM, "publishId": 1, "positionName": ""},
            {**REAL_ITEM, "publishId": 2, "positionName": "正常岗"},
        ]
        jobs = JdCampusAdapter().parse(_raw(items))
        self.assertEqual([j.title for j in jobs], ["正常岗"])

    def test_没有_requirementVoList_时城市为空但不炸(self):
        item = {k: v for k, v in REAL_ITEM.items() if k != "requirementVoList"}
        jobs = JdCampusAdapter().parse(_raw([item]))
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0].location)
        self.assertIn("结合时事热点", jobs[0].summary, "没有城市也要保住正文")

    def test_空列表与脏输入不炸(self):
        a = JdCampusAdapter()
        self.assertEqual(a.parse(_raw([])), [])
        self.assertEqual(a.parse("not json"), [])
        self.assertEqual(a.parse(json.dumps({"_intercepted": []})), [])


class JdCampusTotalTest(unittest.TestCase):
    def test_总数键是_totalNumber(self):
        # 用 total/count 命名的响应拿不到数 —— 钉死这一点，防止有人「顺手」把键名改回常见写法
        self.assertEqual(JdCampusAdapter._reported_total_from_response(_resp([], total=126)), 126)

    def test_没有总数时返回_None_而不是编一个(self):
        self.assertIsNone(JdCampusAdapter._reported_total_from_response({"success": True, "body": {"items": []}}))


class JdCampusWiringTest(unittest.TestCase):
    def test_已注册且不在_httpx_安全档(self):
        import run
        self.assertIn("jd_campus", run.ADAPTERS)
        self.assertIsInstance(run.ADAPTERS["jd_campus"], JdCampusAdapter)
        # 它需要浏览器（httpx 直调列表接口会被风控换成 JDOA 拦截页）
        self.assertNotIn("jd_campus", run._HTTPX_SAFE_ADAPTERS)


if __name__ == "__main__":
    unittest.main()
