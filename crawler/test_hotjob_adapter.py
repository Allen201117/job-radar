"""HotJob / wecruit 通用 adapter 单测 — 构造公开列表接口响应，不打真实网络。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import normalizer
from adapters.hotjob import HotJobAdapter


TCL_LIST_RESPONSE = {
    "data": {
        "pageForm": {
            "pageData": [
                {
                    "postId": "69a2980b8e515379dcfe3dc6",
                    "postName": "BW/HANA顾问",
                    "workPlaceStr": "深圳市",
                    "postTypeName": "研发技术类",
                    "workContent": "负责 BW/HANA 系统建设。",
                    "serviceCondition": "本科及以上。",
                    "publishDate": "2026-06-05 14:06:32",
                },
                {
                    "postId": "missing-title",
                    "workPlaceStr": "深圳市",
                },
            ]
        }
    }
}


class TestHotJobAdapter(unittest.TestCase):
    def setUp(self):
        self.a = HotJobAdapter()
        self.a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html")

    def test_bind_source_builds_detail_template_and_list_urls(self):
        self.assertEqual(self.a._suite_key, "SU64893571bef57c16d356b99e")
        self.assertEqual(self.a.official_hosts, ("wecruit.hotjob.cn",))
        self.assertIn(
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html",
            self.a.list_urls,
        )
        self.assertEqual(
            self.a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=society",
        )

    def test_bind_source_maps_school_and_intern_detail_post_type(self):
        a = HotJobAdapter()
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/school.html")
        self.assertEqual(
            a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=campus",
        )
        a._bind_source("https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/interns.html")
        self.assertEqual(
            a.detail_template,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId={id}&postType=intern",
        )

    def test_parse_list_position_builds_detail_jobs(self):
        jobs = self.a.parse(json.dumps({"_intercepted": [TCL_LIST_RESPONSE]}))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].title, "BW/HANA顾问")
        self.assertEqual(jobs[0].location, "深圳市")
        self.assertEqual(jobs[0].job_type, "研发技术类")
        self.assertEqual(jobs[0].posted_at, "2026-06-05")
        self.assertEqual(
            jobs[0].jd_url,
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/posDetail.html?postId=69a2980b8e515379dcfe3dc6&postType=society",
        )
        self.assertIn("负责 BW/HANA", jobs[0].summary)
        self.assertIn("本科及以上", jobs[0].summary)

    def test_quality_gate_passes_hotjob_detail_url(self):
        jobs = self.a.parse(json.dumps({"_intercepted": [TCL_LIST_RESPONSE]}))
        jobs[0].company = "TCL"
        ok, reason = normalizer.validate_job_quality(
            jobs[0],
            "https://wecruit.hotjob.cn/SU64893571bef57c16d356b99e/pb/social.html",
        )
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
