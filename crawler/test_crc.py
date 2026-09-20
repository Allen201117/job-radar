"""华润集团招聘平台 adapter 的契约测试（纯函数，不打真实网络）。

每条断言对应一个 2026-09-20 live 实测出来的坑，改代码时它们会先红：
  · 详情页 id 必须是 blockRowId 而不是 id（两者只差 1，用错 = 全源死链）
  · Time_Stamp 必须是北京时间（runner 是 UTC，用错 = HTTP 200 + 空 body 的「假绿」）
  · 四个自定义请求头缺一不可
  · 空 body 必须抛错，不许安静返 0 条
"""
import base64
import json
import unittest
from datetime import datetime
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from adapters.crc import CrcAdapter

SITE = "2092202183442501634"
HOMEPAGE = f"https://runjob.crc.com.cn/#/homepage?id={SITE}"

# 真实响应行的形状（字段名取自 2026-09-20 live 抓到的记录，注意 id 与 blockRowId 差 1）
ROW = {
    "blockRowId": "2094613448621518850",
    "id": "2094613448621518849",
    "pubPositionName": "合规管理岗",
    "companyDescr": "华润三九医药股份有限公司",
    "locationDescr": "中国,广东,深圳市",
    "publishDate": "2026-09-01",
    "typeId": "A01",
    "typeIdDescr": "社会招聘",
    "educationalRqmtDescr": "本科及以上",
    "workYearsRqmtDescr": "3-5年",
    "rmJobDuty": "负责合规管理体系落地",
    "rmJobRqmt": "本科及以上学历，法律相关专业优先",
    "_channel": "社会招聘",
    "_site_id": SITE,
}


def _parse_one(**overrides):
    row = dict(ROW)
    row.update(overrides)
    return CrcAdapter().parse(json.dumps({"records": [row]}, ensure_ascii=False))


class SiteId(unittest.TestCase):
    def test_reads_brand_site_id_from_hash_query(self):
        self.assertEqual(CrcAdapter._site_id(HOMEPAGE), SITE)
        self.assertEqual(
            CrcAdapter._site_id(f"https://runjob.crc.com.cn/#/position?id=x&websiteId={SITE}"), "x")

    def test_missing_id_returns_empty_not_crash(self):
        for url in ("https://runjob.crc.com.cn/", "https://runjob.crc.com.cn/#/homepage", "", None):
            self.assertEqual(CrcAdapter._site_id(url), "")

    def test_fetch_refuses_source_url_without_site_id(self):
        with self.assertRaises(RuntimeError):
            CrcAdapter().fetch("https://runjob.crc.com.cn/")


class DetailUrlUsesBlockRowId(unittest.TestCase):
    """用 id 而不是 blockRowId，详情页会渲染成「职位已下架」——live 逐个核过。"""

    def test_jd_url_carries_block_row_id_and_never_the_other_id(self):
        job = _parse_one()[0]
        self.assertIn("id=2094613448621518850", job.jd_url)
        self.assertNotIn("2094613448621518849", job.jd_url)
        self.assertEqual(job.apply_url, job.jd_url)
        self.assertIn(f"websiteId={SITE}", job.jd_url)
        self.assertIn("typeId=A01", job.jd_url)

    def test_row_without_block_row_id_is_dropped_even_if_id_present(self):
        # 只有 id 没有 blockRowId 时宁可丢这条，也不能拿 id 拼出一个必然死链的 jd_url
        self.assertEqual(_parse_one(blockRowId=""), [])

    def test_row_without_title_is_dropped(self):
        self.assertEqual(_parse_one(pubPositionName=""), [])


class FieldMapping(unittest.TestCase):
    def test_company_is_platform_declared_legal_entity(self):
        self.assertEqual(_parse_one()[0].company, "华润三九医药股份有限公司")
        self.assertEqual(_parse_one(companyDescr="昆药集团股份有限公司")[0].company, "昆药集团股份有限公司")

    def test_job_type_is_platform_declared_channel_name(self):
        # 招聘类型分类器读它；平台自报的类别比任何猜测都准
        self.assertEqual(_parse_one()[0].job_type, "社会招聘")
        self.assertEqual(_parse_one(typeIdDescr="校园招聘")[0].job_type, "校园招聘")

    def test_summary_merges_duty_and_requirement(self):
        summary = _parse_one()[0].summary
        self.assertIn("负责合规管理体系落地", summary)
        self.assertIn("法律相关专业优先", summary)

    def test_other_fields(self):
        job = _parse_one()[0]
        self.assertEqual(job.location, "中国,广东,深圳市")
        self.assertEqual(job.posted_at, "2026-09-01")
        self.assertEqual(job.education, "本科及以上")
        self.assertEqual(job.experience, "3-5年")

    def test_parse_tolerates_garbage(self):
        self.assertEqual(CrcAdapter().parse("not json"), [])
        self.assertEqual(CrcAdapter().parse(json.dumps({"records": []})), [])


class GatewayContract(unittest.TestCase):
    def test_timestamp_is_beijing_time_not_utc(self):
        """runner 跑 UTC；用 UTC 时间戳网关返 200 + 零字节 body（静默 0 产出）。"""
        decoded = base64.b64decode(CrcAdapter()._ssdp()).decode()
        stamp = parse_qs(decoded)["Time_Stamp"][0]
        sent = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")
        now_sh = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
        self.assertLess(abs((sent - now_sh).total_seconds()), 120,
                        f"Time_Stamp {stamp} 不是北京时间当下（网关只认几分钟内的北京时间）")

    def test_ssdp_declares_anonymous_access(self):
        decoded = base64.b64decode(CrcAdapter()._ssdp()).decode()
        self.assertIn("Sign=NO_SIGN", decoded)
        self.assertTrue(decoded.endswith("User_Token="))

    def test_source_pins_shanghai_zone(self):
        """防止有人把 ZoneInfo 换成 datetime.now()——单测在本机(上海)照样会绿，只有 CI 会坏。"""
        import inspect
        import adapters.crc as mod
        src = inspect.getsource(mod)
        self.assertIn('ZoneInfo("Asia/Shanghai")', src)
        self.assertNotIn("datetime.utcnow", src)

    def test_required_custom_headers_present(self):
        headers = CrcAdapter()._headers(SITE)
        for key in ("homepageconfigid", "languageindex", "rmapplyid", "authorization"):
            self.assertIn(key, headers, f"缺 {key} 会让网关返 200 + 空 body")
        self.assertEqual(headers["homepageconfigid"], SITE)

    def test_empty_body_raises_instead_of_reporting_zero(self):
        class _Resp:
            content = b""
            def raise_for_status(self):
                return None
        class _Client:
            def post(self, *_a, **_kw):
                return _Resp()
        with self.assertRaises(RuntimeError) as ctx:
            CrcAdapter()._call(_Client(), SITE, "searchPublishPosition", {})
        self.assertIn("empty body", str(ctx.exception))

    def test_missing_return_data_raises(self):
        class _Resp:
            content = b'{"RESPONSE":{"RETURN_CODE":"X","RETURN_DESC":"boom"}}'
            def raise_for_status(self):
                return None
            def json(self):
                return json.loads(self.content)
        class _Client:
            def post(self, *_a, **_kw):
                return _Resp()
        with self.assertRaises(RuntimeError):
            CrcAdapter()._call(_Client(), SITE, "searchPublishPosition", {})


class Registration(unittest.TestCase):
    def test_registered_as_httpx_safe_and_domestic(self):
        import run
        self.assertIn("crc", run.ADAPTERS)
        self.assertIn("crc", run._HTTPX_SAFE_ADAPTERS)
        self.assertIn("crc", run.DOMESTIC_ADAPTERS)


if __name__ == "__main__":
    unittest.main()
