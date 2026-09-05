"""四家国有大行 + 浦发 + 中国移动自建门户 adapter 的纯函数测试（不打真实网络）。

重点钉住的是三类「安静出错」的行为，它们都不会抛异常、只会让数据悄悄变错：
  · jd_url 的形态（少一个参数就打不开 / 招聘类型选错前缀 → 详情页打不开）
  · 「报名已截止」的岗不许进库（列表接口会照样返给你）
  · 接口用 HTTP 200 表达失败（工行 retCode / 中国移动 code / 交行 TRAN_SUCCESS）
"""
import json
import pathlib
import ssl
import unittest
from datetime import date, timedelta

from adapters.abchina import AbchinaAdapter
from adapters.bankcomm import BankcommAdapter
from adapters.ccb import CcbAdapter, _repair_json
from adapters.cmcc import CmccAdapter, _rsa_public_numbers, _PUBLIC_KEY_SPKI
from adapters.icbc import IcbcAdapter
from adapters.cn_portal_tls import make_ssl_context, make_transport
from adapters.spdb import SpdbAdapter


class SpdbAdapterTest(unittest.TestCase):
    def test_parse_maps_recruit_type_to_detail_type_code(self):
        payload = {"jobs": [
            {"openningJobId": "10023076", "positionName": "客服代表岗", "prmLocArea": "上海",
             "recuitType": "11", "desiredStartDt": "2026-07-29", "closeDt": "2027-07-28",
             "_detail_body": "客服代表岗 数字平台部 岗位职责 接听客户来电"},
            {"openningJobId": "10023420", "positionName": "总行管理培训生", "prmLocArea": "上海",
             "recuitType": "12", "desiredStartDt": "2026-09-03", "closeDt": "2026-10-08",
             "hpsDegreeRql": "硕士及以上", "_detail_body": "总行管理培训生 总行 应聘条件 硕士"},
        ]}
        social, campus = SpdbAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(social.job_type, "社招")
        self.assertEqual(social.jd_url,
                         "https://job.spdb.com.cn/jobDetail?jobId=10023076&type=1")
        # 正文开头会重复一遍岗位名，去掉前缀免得 summary 以标题开头。
        self.assertTrue(social.summary.startswith("数字平台部"))

        self.assertEqual(campus.job_type, "校招")
        self.assertEqual(campus.jd_url,
                         "https://job.spdb.com.cn/jobDetail?jobId=10023420&type=2")
        self.assertEqual(campus.education, "硕士及以上")

    def test_sentinel_close_date_is_not_a_real_deadline(self):
        payload = {"jobs": [{"openningJobId": "1", "positionName": "常青岗",
                             "recuitType": "11", "closeDt": "2100-12-31"}]}
        job = SpdbAdapter().parse(json.dumps(payload, ensure_ascii=False))[0]
        self.assertIsNone(job.deadline)

    def test_detail_body_is_cut_between_template_anchors(self):
        html = ("<html><body><div>导航 返回列表</div>"
                "<div>产品经理岗 岗位职责 负责产品设计</div>"
                "<footer>All rights reserved 2026.</footer></body></html>")
        self.assertEqual(SpdbAdapter._detail_body(html), "产品经理岗 岗位职责 负责产品设计")
        # 锚点缺失（例如错误页）不许把整页当正文。
        self.assertEqual(SpdbAdapter._detail_body("<html><body>500 出错了</body></html>"), "")


class IcbcAdapterTest(unittest.TestCase):
    def test_campus_and_social_use_different_hash_sections(self):
        payload = {"jobs": [
            {"postId": "p1", "publishPostName": "总行管理培训生", "placeStr": "中国-北京市",
             "_job_type": "校招", "_section": "school", "publishTime": "2026-09-04 13:59:24",
             "enterEndTime": "2026-10-08 23:59:00", "_depict": "培养目标：综合管理人才"},
            {"postId": "p2", "publishPostName": "云计算技术研发岗", "placeStr": "浙江省-杭州市",
             "_job_type": "社招", "_section": "social", "enterEndTime": "2026-12-31 23:59:59"},
        ]}
        campus, social = IcbcAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(campus.jd_url,
                         "https://job.icbc.com.cn/pc/index.html#/main/school/postDetail/p1")
        self.assertEqual(campus.location, "北京市")
        self.assertEqual(campus.deadline, "2026-10-08")
        self.assertEqual(social.jd_url,
                         "https://job.icbc.com.cn/pc/index.html#/main/social/postDetail/p2")
        self.assertEqual(social.location, "杭州市")

    def test_expired_postings_are_dropped(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.assertFalse(IcbcAdapter._is_open({"enterEndTime": f"{yesterday} 23:59:59"}, today))
        self.assertTrue(IcbcAdapter._is_open({"enterEndTime": f"{today} 23:59:59"}, today))
        # 缺截止日不代表已过期——保守放行，交给下游探活判死。
        self.assertTrue(IcbcAdapter._is_open({}, today))

    def test_head_precheck_is_disabled(self):
        # job.icbc.com.cn 对 HEAD 恒返 403（换浏览器 UA 也一样），GET/POST 正常。
        # 不覆写 should_skip 就会被判「被拒」而整源跳过、永远抓不到岗。
        self.assertIsNone(IcbcAdapter().should_skip("https://job.icbc.com.cn/pc/index.html"))

    def test_reported_total_counts_only_what_we_keep(self):
        # 官网把报名已截止的岗也列在列表里（社招 63 条里 15 条已截止）。拿含过期岗的
        # 自报总数当分母，crawl_runs 上会永远挂着「自报 2630 / 只入库 2615」这个**假缺口** ——
        # 那 15 条是我们主动丢的，不是漏抓的。
        src = pathlib.Path(__file__).resolve().parent / "adapters" / "icbc.py"
        self.assertIn("self.reported_total = len(open_rows)", src.read_text(encoding="utf-8"))

    def test_depict_is_base64_urlencoded_html(self):
        import base64
        import urllib.parse
        raw = "<p>负责&nbsp;云平台研发</p>"
        encoded = base64.b64encode(urllib.parse.quote(raw).encode()).decode()
        self.assertEqual(IcbcAdapter._decode_depict(encoded), "负责 云平台研发")
        # 解不开就当没有正文，不能炸掉整轮抓取。
        self.assertEqual(IcbcAdapter._decode_depict("not-base64!!"), "")


class CcbAdapterTest(unittest.TestCase):
    def test_jd_url_carries_all_five_required_params(self):
        payload = {"jobs": [{
            "planId": "2026090108928217", "planPost": "20260901111102543884",
            "planPostName": "科技类专项人才", "planType": "XY", "workPlace": "北京市",
            "orgId": "2005978", "secondOrgId": "20210517152000681738",
            "postDate": "2026-09-04", "endDate": "2026-10-08", "_job_type": "校招",
            "_detail": {"postDesc": "主要从事人工智能", "PostRequest": "本科及以上"},
        }]}
        job = CcbAdapter().parse(json.dumps(payload, ensure_ascii=False))[0]

        # 前端 getRequireParam('planId,planPost,orgId,secondOrgId') 缺一个就 alert 并回退，
        # 所以这五个参数一个都不能少 —— 这条断言就是那个契约。
        self.assertEqual(
            job.jd_url,
            "https://job3.ccb.com/cn/job/job_detail.html"
            "?planId=2026090108928217&planPost=20260901111102543884&planType=XY"
            "&orgId=2005978&secondOrgId=20210517152000681738",
        )
        self.assertEqual(job.summary, "【岗位职责】\n主要从事人工智能\n【岗位要求】\n本科及以上")

    def test_repair_json_handles_raw_newlines_inside_values(self):
        broken = '{"SUCCESS":"true","postDesc":"第一行\n第二行\t带制表"}'
        self.assertEqual(_repair_json(broken)["postDesc"], "第一行\n第二行\t带制表")

    def test_empty_body_is_an_error_not_zero_jobs(self):
        # Bot UA 换来的是 HTTP 200 + 零字节；安静返 0 条就是「绿灯零产出」。
        with self.assertRaises(RuntimeError):
            _repair_json("   ")

    def test_closed_postings_are_filtered_after_aggregation(self):
        # 与 bankcomm/icbc 同一条不变量：全部报名结束时不能抛异常（那是正常状态不是故障），
        # 且分母只算还能报名的岗，免得抓全率上永远挂个假缺口。
        src = pathlib.Path(__file__).resolve().parent / "adapters" / "ccb.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn('open_rows = [r for r in rows if str(r.get("planStatus") or "") != "2"]', text)
        self.assertIn("self.reported_total = len(open_rows)", text)
        self.assertIn('return json.dumps({"jobs": open_rows}', text)

    def test_detail_empty_body_does_not_kill_the_whole_run(self):
        # _repair_json 空 body 抛的是 RuntimeError；detail 循环要是漏捕它，
        # 一次限速空响应就会穿透 fetch，把**已经抓全的 3,799 条列表**一起作废、记 failed。
        src = pathlib.Path(__file__).resolve().parent / "adapters" / "ccb.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("except (httpx.HTTPError, json.JSONDecodeError, RuntimeError):", text)

    def test_detail_only_accepts_explicit_success(self):
        # 缺 SUCCESS 字段的错误骨架不能被当成详情塞进 _detail。
        src = pathlib.Path(__file__).resolve().parent / "adapters" / "ccb.py"
        self.assertIn('detail.get("SUCCESS") == "true"', src.read_text(encoding="utf-8"))

    def test_bot_user_agent_is_overridden(self):
        self.assertNotIn("JobRadarBot", CcbAdapter.user_agent)


class BankcommAdapterTest(unittest.TestCase):
    def test_social_and_campus_sections_and_workplace_cleanup(self):
        payload = {"jobs": [
            {"positionId": 38473, "pubName": "客户经理", "workPlace": "天津-辖区",
             "createTime": "2026-08-19 11:38:22", "endDate": "2026-09-30",
             "_job_type": "社招", "_section": "social",
             "_detail": {"responsibility": "做好营销工作", "require": "身体健康"}},
            {"positionId": 40001, "pubName": "管培生", "workPlace": "上海-辖区",
             "endDate": "2026-12-31", "_job_type": "校招", "_section": "school"},
        ]}
        social, campus = BankcommAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(social.jd_url,
                         "https://job.bankcomm.com/#/social/recruitmentInfo/?positionId=38473")
        self.assertEqual(social.location, "天津")
        self.assertEqual(social.summary, "【职位描述】\n做好营销工作\n【职位要求】\n身体健康")
        self.assertEqual(campus.jd_url,
                         "https://job.bankcomm.com/#/school/recruitmentInfo/?positionId=40001")

    def test_expired_postings_are_dropped(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.assertFalse(BankcommAdapter._is_open({"endDate": yesterday}, today))
        self.assertTrue(BankcommAdapter._is_open({"endDate": today}, today))

    def test_all_expired_is_not_a_failure(self):
        # 招聘窗口刚结束那几天所有岗都过期。若过期过滤放在聚合处做，rows 会是空的 →
        # 抛 RuntimeError → 源被记 failed 并触发告警，而接口其实好好的。
        # 「没有在招岗」是正常状态，不是故障 —— 所以 `if not rows` 必须看**未过滤**的行。
        src = pathlib.Path(__file__).resolve().parent / "adapters" / "bankcomm.py"
        text = src.read_text(encoding="utf-8")
        self.assertIn("open_rows = [r for r in rows if self._is_open(r, today)]", text)
        self.assertIn('return json.dumps({"jobs": open_rows}', text)


class CmccAdapterTest(unittest.TestCase):
    def test_campus_detail_url_carries_typess_like_the_site_does(self):
        payload = {"jobs": [
            {"id": "uuid-campus", "name": "南宁分公司-计算机/数据类", "type": "1",
             "province": "广西壮族自治区", "city": "南宁市",
             "startTime": "2026-09-05", "endTime": "2026-10-31",
             "description": "IT 维护", "dutyCondition": "计算机相关专业"},
            {"id": "uuid-social", "name": "执纪审查", "type": "2",
             "province": "北京市", "city": "北京市"},
        ]}
        campus, social = CmccAdapter().parse(json.dumps(payload, ensure_ascii=False))

        self.assertEqual(campus.job_type, "校招")
        self.assertEqual(
            campus.jd_url,
            "https://job.10086.cn/personal/job/detail.html?id=uuid-campus&typess=1")
        self.assertEqual(campus.location, "广西壮族自治区南宁市")
        self.assertEqual(campus.summary, "【岗位描述】\nIT 维护\n【任职条件】\n计算机相关专业")

        self.assertEqual(social.job_type, "社招")
        self.assertEqual(social.jd_url,
                         "https://job.10086.cn/personal/job/detail.html?id=uuid-social")
        # 省市同名时不重复拼接。
        self.assertEqual(social.location, "北京市")

    def test_head_precheck_is_disabled(self):
        # job.10086.cn 对 HEAD 恒返 403（换 UA 无效），不覆写就整源被跳过。
        self.assertIsNone(CmccAdapter().should_skip("https://job.10086.cn/personal/job/"))

    def test_public_key_parses_to_the_sites_2048_bit_rsa_key(self):
        modulus, exponent = _rsa_public_numbers(_PUBLIC_KEY_SPKI)
        self.assertEqual(modulus.bit_length(), 2048)
        self.assertEqual(exponent, 65537)


class CnPortalTlsTest(unittest.TestCase):
    """这两条在本机永远是绿的（LibreSSL 宽松 + 有 IPv6），只有 CI 会炸——所以必须有断言看着。"""

    def test_context_allows_legacy_renegotiation_but_keeps_verification(self):
        ctx = make_ssl_context()
        self.assertTrue(ctx.options & 0x4, "缺 OP_LEGACY_SERVER_CONNECT：OpenSSL 3 会拒建行/交行/移动")
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED, "不许为了绕重协商把证书校验也关了")
        self.assertTrue(ctx.check_hostname)

    def test_transport_pins_ipv4(self):
        # 这几家都有 AAAA 记录，而 GitHub runner 没有可用 IPv6 出口 → 不钉 IPv4 就是 Errno 101。
        self.assertEqual(make_transport()._pool._local_address, "0.0.0.0")

    def test_every_httpx_bank_adapter_uses_it(self):
        import pathlib
        base = pathlib.Path(__file__).resolve().parent / "adapters"
        for name in ("spdb", "icbc", "ccb", "bankcomm", "cmcc"):
            src = (base / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("transport=make_transport()", src,
                          f"{name} 没走兼容 transport，上了 CI 会 SSL/IPv6 失败")


class AbchinaAdapterTest(unittest.TestCase):
    def test_jd_url_keeps_the_literal_colon_the_site_puts_there(self):
        payload = {"jobs": [{
            "jobPublishId": 155541420, "posName": "软件研发岗", "workplace": "北京",
            "deadline": "2026-10-08", "orgName": "农银金科", "_job_type": "校招",
        }]}
        job = AbchinaAdapter().parse(json.dumps(payload, ensure_ascii=False))[0]

        # 站点自己的 onClick 拼的就是 '#/PositionDetails/:' + jobPublishId —— 冒号是字面量。
        # 去掉它详情页打不开，所以这条断言钉的是「别自作聪明把冒号当占位符删掉」。
        self.assertEqual(
            job.jd_url,
            "https://career.abchina.com/build/index.html#/PositionDetails/:155541420")
        self.assertEqual(job.location, "北京")
        self.assertEqual(job.job_type, "校招")
        self.assertEqual(job.deadline, "2026-10-08")
        # 正文只在逐岗详情页，列表侧一个字都没有——不许假装有。
        self.assertIsNone(job.summary)

    def test_rows_without_id_or_title_are_dropped(self):
        payload = {"jobs": [{"jobPublishId": 1}, {"posName": "无 id 岗"}, {}]}
        self.assertEqual(AbchinaAdapter().parse(json.dumps(payload)), [])

    def test_is_not_in_the_httpx_concurrency_lane(self):
        # 它要起 Playwright（响应体加密，明文只在浏览器里），进并发档会把 sync API 跑崩。
        import sys, pathlib as _p
        sys.path.insert(0, str(_p.Path(__file__).resolve().parent))
        import run
        self.assertIn("abchina", run.ADAPTERS)
        self.assertIn("abchina", run.DOMESTIC_ADAPTERS)
        self.assertFalse(run._is_httpx_safe("abchina"))


if __name__ == "__main__":
    unittest.main()
