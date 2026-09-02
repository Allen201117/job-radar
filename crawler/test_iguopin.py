"""国聘公开接口 fixture：离线运行，不访问网络。"""
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from adapters.iguopin import IguopinAdapter, _company_keyword


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _job(job_id, company_name, company_id):
    return {
        "job_id": str(job_id),
        "job_name": f"岗位 {job_id}",
        "company_id": str(company_id),
        "company_name": company_name,
        "contents": f"岗位 {job_id} 职责",
    }


class IguopinAdapterTest(unittest.TestCase):
    def test_parse_verified_detail_job(self):
        fixture = Path(__file__).with_name("fixtures") / "iguopin_list.json"
        row = json.loads(fixture.read_text(encoding="utf-8"))["data"]["list"][0]
        row["_detail_verified"] = True
        row["_jd"] = row["contents"]  # GET /api/jobs/v1/info?id=... 的真实 data.contents

        jobs = IguopinAdapter().parse(json.dumps({"list": [row]}, ensure_ascii=False))

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "技术总工（道路、隧道）")
        self.assertEqual(jobs[0].jd_url,
                         "https://www.iguopin.com/job/detail?id=205308503458317218")
        self.assertGreaterEqual(len(jobs[0].summary or ""), 60)
        self.assertEqual(jobs[0].deadline, "2026-09-14 23:59:59")

    def test_parse_rejects_unverified_list_item(self):
        jobs = IguopinAdapter().parse(json.dumps({"list": [{"job_id": "1", "job_name": "岗位"}]}))
        self.assertEqual(jobs, [])

    def test_source_url_company_keyword(self):
        self.assertEqual(
            _company_keyword("https://www.iguopin.com/job?company=%E4%B8%AD%E5%9B%BD%E5%BB%BA%E7%AD%91"),
            "中国建筑")

    def test_zero_detail_cap_skips_before_list_request(self):
        with mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "0"}, clear=False), \
             mock.patch("adapters.iguopin.httpx.post") as post:
            reason = IguopinAdapter().should_skip("https://www.iguopin.com/job?company=国家电网")

        self.assertIn("requires detail verification", reason)
        post.assert_not_called()

    def test_positive_detail_cap_keeps_source_eligible(self):
        with mock.patch.dict(os.environ, {"CRAWL_DETAIL_CAP": "1"}, clear=False):
            self.assertIsNone(IguopinAdapter().should_skip("https://www.iguopin.com/job?company=国家电网"))

    def test_fetch_expands_group_children_and_labels_jobs_with_group_brand(self):
        """防止国聘又只停在模糊搜索命中的边缘子公司。"""
        root = _job("root", "国网国际融资租赁有限公司", "child-root")
        jiangsu = _job("js", "国网江苏省电力有限公司", "child-js")
        hubei = _job("hb", "国网湖北省电力有限公司", "child-hb")
        searched = []

        def fake_post(_url, **kwargs):
            keyword = kwargs["json"]["search"]["keyword"]
            searched.append(keyword)
            rows = {
                "国家电网": [root],
                "国网江苏省电力有限公司": [jiangsu],
                "国网湖北省电力有限公司": [hubei],
            }[keyword]
            return _Response({"code": 200, "data": {"total": len(rows), "list": rows}})

        def fake_get(url, **kwargs):
            if "company/index/v1/home" in url:
                self.assertEqual(kwargs["params"], {"company_id": "child-root"})
                return _Response({"code": 200, "data": {"company_info": {
                    "id": "child-root", "group_id": "group-grid", "group_short_name": "国家电网",
                }}})
            if "children-list" in url:
                self.assertEqual(kwargs["params"], {"company_id": "group-grid"})
                return _Response({"code": 200, "data": [
                    {"name": "国网江苏省电力有限公司"},
                    {"company_name": "国网湖北省电力有限公司"},
                ]})
            job_id = kwargs["params"]["id"]
            row = {"root": root, "js": jiangsu, "hb": hubei}[job_id]
            return _Response({"code": 200, "data": {**row, "contents": row["contents"]}})

        with mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get):
            payload = IguopinAdapter().fetch("https://www.iguopin.com/job?company=国家电网&match=国家电网")

        jobs = IguopinAdapter().parse(payload)
        self.assertEqual(searched, ["国家电网", "国网江苏省电力有限公司", "国网湖北省电力有限公司"])
        self.assertEqual(
            [job.company for job in jobs],
            [
                "国网江苏省电力有限公司（国家电网）",
                "国网湖北省电力有限公司（国家电网）",
            ],
        )

    def test_fetch_keeps_keyword_results_when_group_lookup_fails(self):
        """防止新增集团接口故障把原本可抓的国聘源整体打失败。"""
        root = _job("root", "国网国际融资租赁有限公司", "child-root")
        searched = []

        def fake_post(_url, **kwargs):
            searched.append(kwargs["json"]["search"]["keyword"])
            return _Response({"code": 200, "data": {"total": 1, "list": [root]}})

        def fake_get(url, **kwargs):
            if "company/index/v1/home" in url:
                raise RuntimeError("group endpoint unavailable")
            return _Response({"code": 200, "data": {**root, "contents": root["contents"]}})

        with mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get):
            payload = IguopinAdapter().fetch("https://www.iguopin.com/job?company=国家电网")

        jobs = IguopinAdapter().parse(payload)
        self.assertEqual(searched, ["国家电网"])
        self.assertEqual([job.company for job in jobs], ["国网国际融资租赁有限公司"])

    def test_fetch_only_verifies_rows_matching_match_token(self):
        matched = _job("matched", "中国石油天然气集团有限公司", "company-1")
        unrelated = _job("unrelated", "中国石化销售有限公司", "company-2")

        def fake_post(_url, **_kwargs):
            return _Response({"code": 200, "data": {"total": 2, "list": [matched, unrelated]}})

        def fake_get(_url, **kwargs):
            self.assertEqual(kwargs["params"]["id"], "matched")
            return _Response({"code": 200, "data": {**matched, "contents": matched["contents"]}})

        with mock.patch.object(IguopinAdapter, "_expand_group_children", return_value=None), \
             mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get) as get:
            IguopinAdapter().fetch("https://www.iguopin.com/job?company=中国石油&match=中国石油")

        self.assertEqual(get.call_count, 1)

    def test_fetch_verifies_group_child_despite_non_matching_company_name(self):
        root = _job("root", "中国石油天然气集团有限公司", "company-1")
        child = _job("child", "大庆油田有限责任公司", "company-2")

        def fake_post(_url, **_kwargs):
            return _Response({"code": 200, "data": {"total": 1, "list": [root]}})

        def add_group_child(rows, _headers):
            child["_group_child"] = True
            rows.append(child)
            return "中国石油"

        def fake_get(_url, **kwargs):
            job_id = kwargs["params"]["id"]
            row = {"root": root, "child": child}[job_id]
            return _Response({"code": 200, "data": {**row, "contents": row["contents"]}})

        with mock.patch.object(IguopinAdapter, "_expand_group_children", side_effect=add_group_child), \
             mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get) as get:
            IguopinAdapter().fetch("https://www.iguopin.com/job?company=中国石油&match=中国石油")

        detail_ids = [call.kwargs["params"]["id"] for call in get.call_args_list
                      if "jobs/v1/info" in call.args[0]]
        self.assertEqual(set(detail_ids), {"root", "child"})

    def test_fetch_without_match_verifies_all_rows_within_detail_cap(self):
        rows = [_job(str(index), f"公司 {index}", f"company-{index}") for index in range(3)]

        def fake_post(_url, **_kwargs):
            return _Response({"code": 200, "data": {"total": len(rows), "list": rows}})

        def fake_get(_url, **kwargs):
            job_id = kwargs["params"]["id"]
            row = next(row for row in rows if row["job_id"] == job_id)
            return _Response({"code": 200, "data": {**row, "contents": row["contents"]}})

        with mock.patch.object(IguopinAdapter, "_DETAIL_CAP", 2), \
             mock.patch.object(IguopinAdapter, "_expand_group_children", return_value=None), \
             mock.patch("adapters.iguopin.httpx.post", side_effect=fake_post), \
             mock.patch("adapters.iguopin.httpx.get", side_effect=fake_get) as get:
            IguopinAdapter().fetch("https://www.iguopin.com/job?company=任意公司")

        detail_ids = [call.kwargs["params"]["id"] for call in get.call_args_list
                      if "jobs/v1/info" in call.args[0]]
        self.assertEqual(set(detail_ids), {"0", "1"})

    def test_company_group_brand_label_avoids_duplicates_and_group_self(self):
        """防止展示名重复品牌，或把集团自身写成冗余括号后缀。"""
        rows = []
        for index, company in enumerate((
            "国网江苏省电力有限公司",
            "国网江苏省电力有限公司（国家电网）",
            "国家电网有限公司",
        )):
            row = _job(index, company, index)
            row["_detail_verified"] = True
            rows.append(row)

        jobs = IguopinAdapter().parse(json.dumps({
            "list": rows,
            "_group_short_name": "国家电网",
        }, ensure_ascii=False))

        self.assertEqual([job.company for job in jobs], [
            "国网江苏省电力有限公司（国家电网）",
            "国网江苏省电力有限公司（国家电网）",
            "国家电网有限公司",
        ])


if __name__ == "__main__":
    unittest.main()
