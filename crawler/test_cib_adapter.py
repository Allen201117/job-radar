import json
import unittest

import normalizer
from adapters.cib import CibAdapter, collect_pages


def _row(pid="1280466164486230016", **over):
    row = {"positionId": pid, "positionName": "对公客户经理（劳务派遣）", "recruitType": "SR",
           "businessUnitDesc": "西安分行", "positionAddr": "陕西省西安市,陕西省榆林市",
           "jobDuty": "1.负责建立和维护客户关系，组织实施客户营销工作，负责业务落地操作和存续期管理等工作；",
           "positionRequirment": "一、基本要求\n1.遵纪守法，诚实守信，无违规违纪或其他不良行为记录；",
           "publishTime": "2026-09-23 00:00:00", "expiryDate": "3000-01-01 09:41:24"}
    row.update(over)
    return row


class CollectPagesTest(unittest.TestCase):
    def test_collects_until_reported_total_and_claims_complete(self):
        pages = {1: {"code": "0000", "total": 3, "list": [_row("1"), _row("2")]},
                 2: {"code": "0000", "total": 3, "list": [_row("3")]}}
        rows, total, complete = collect_pages(lambda i: pages[i], page_size=2)
        self.assertEqual(([r["positionId"] for r in rows], total, complete), (["1", "2", "3"], 3, True))

    def test_short_of_total_never_claims_complete(self):
        # 翻页中途排序漂移、同一岗出现两次 → 去重后少一条；抓漏 + 自称抓全 = 误杀在招岗。
        pages = {1: {"code": "0000", "total": 3, "list": [_row("1"), _row("2")]},
                 2: {"code": "0000", "total": 3, "list": [_row("2")]}}
        rows, total, complete = collect_pages(lambda i: pages.get(i, {"code": "0000", "list": []}), page_size=2)
        self.assertEqual((len(rows), total, complete), (2, 3, False))

    def test_error_code_raises(self):
        with self.assertRaises(RuntimeError):
            collect_pages(lambda i: {"code": "1111", "message": "签名校验失败"}, page_size=200)


class ParseTest(unittest.TestCase):
    def test_maps_fields_and_passes_quality_gate(self):
        job = CibAdapter().parse(json.dumps({"jobs": [_row()]}, ensure_ascii=False))[0]
        self.assertEqual(job.title, "对公客户经理（劳务派遣）（西安分行）")
        self.assertEqual(job.jd_url, "https://job.cib.com.cn/portal/recruit/814456617331937281"
                                     "?recruitType=SR#/positionDetails/1280466164486230016")
        self.assertEqual((job.job_type, job.posted_at, job.deadline), ("社招", "2026-09-23", None))
        self.assertIn("【岗位职责】", job.summary)
        self.assertIn("【任职要求】", job.summary)
        self.assertTrue(normalizer.validate_job_quality(
            job, "https://job.cib.com.cn/portal/recruit/814456617331937281?recruitType=SR")[0])

    def test_campus_row_keeps_its_own_recruit_type_and_real_deadline(self):
        job = CibAdapter().parse(json.dumps({"jobs": [_row("1013123084571369472", recruitType="CR",
                                                          positionName="运营支持类", businessUnitDesc="呼和浩特分行",
                                                          expiryDate="2026-10-25 23:59:59")]},
                                            ensure_ascii=False))[0]
        self.assertIn("recruitType=CR#/positionDetails/1013123084571369472", job.jd_url)
        self.assertEqual((job.job_type, job.deadline), ("校招", "2026-10-25"))

    def test_intern_type_and_org_not_duplicated(self):
        job = CibAdapter().parse(json.dumps({"jobs": [_row(recruitType="TR", positionName="西安分行实习生",
                                                          businessUnitDesc="西安分行")]}, ensure_ascii=False))[0]
        self.assertEqual((job.job_type, job.title), ("实习", "西安分行实习生"))

    def test_rows_without_id_or_name_are_dropped(self):
        jobs = CibAdapter().parse(json.dumps({"jobs": [_row(positionId=""), _row(positionName=" ")]},
                                             ensure_ascii=False))
        self.assertEqual(jobs, [])


if __name__ == "__main__":
    unittest.main()
