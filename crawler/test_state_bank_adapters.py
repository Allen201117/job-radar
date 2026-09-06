"""四家国有大行 + 浦发 + 中国移动自建门户 adapter 的纯函数测试（不打真实网络）。

重点钉住的是三类「安静出错」的行为，它们都不会抛异常、只会让数据悄悄变错：
  · jd_url 的形态（少一个参数就打不开 / 招聘类型选错前缀 → 详情页打不开）
  · 「报名已截止」的岗不许进库（列表接口会照样返给你）
  · 接口用 HTTP 200 表达失败（工行 retCode / 中国移动 code / 交行 TRAN_SUCCESS）
"""
import json
import pathlib
import ssl
import time
import unittest
from datetime import date, timedelta
from unittest import mock

from adapters import abchina
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

    def test_collect_tells_empty_apart_from_not_rendered(self):
        """「0 个岗」有两种：这家真没在招（正常）/ 页面没渲染出来（漏抓）。混成一种就会
        「没抓全却自称抓全」—— 线上首轮正是这样比本机少了 162 个岗。"""

        class FakePage:
            def __init__(self, state, body):
                self._state, self._body, self.waits = state, body, 0

            def evaluate(self, _js, _key):
                return self._state

            def inner_text(self, _sel):
                return self._body

            def wait_for_timeout(self, _ms):
                self.waits += 1

        # ① 有卡片 → 立刻返回，且算渲染成功
        found, rendered = AbchinaAdapter._collect(
            FakePage([{"jobPublishId": 1}], "在招岗位"), "posCardInfo", "在招岗位")
        self.assertEqual(len(found), 1)
        self.assertTrue(rendered)

        # ② 没卡片但页面渲染完了 → 这家真没在招，不该拖累 fetch_complete
        AbchinaAdapter.RENDER_TIMEOUT_MS, saved = 0, AbchinaAdapter.RENDER_TIMEOUT_MS
        try:
            found, rendered = AbchinaAdapter._collect(
                FakePage([], "机构公告 在招岗位 岗位类别"), "posCardInfo", "在招岗位")
            self.assertEqual(found, [])
            self.assertTrue(rendered)

            # ③ 没卡片且连页面骨架都没出来 → 是漏抓，必须报 rendered=False
            found, rendered = AbchinaAdapter._collect(
                FakePage([], "人才招聘 个人中心"), "posCardInfo", "在招岗位")
            self.assertEqual(found, [])
            self.assertFalse(rendered)
        finally:
            AbchinaAdapter.RENDER_TIMEOUT_MS = saved

    def test_missed_orgs_get_one_retry_and_then_break_fetch_complete(self):
        src = (pathlib.Path(__file__).resolve().parent / "adapters" / "abchina.py").read_text(encoding="utf-8")
        # 没渲染出来的机构先进 pending，走完所有机构后补一轮（那会儿瞬时拥塞多半过去了）
        self.assertIn("pending.append((recruit_type, job_type, org))", src)
        self.assertIn("for recruit_type, job_type, org in list(pending):", src)
        # 重试还不行才认漏抓，并且**不许再自称抓全**
        self.assertIn("self.fetch_complete = (not truncated) and all_rendered", src)

    def test_summary_is_composed_from_the_three_detail_sections(self):
        payload = {"jobs": [{
            "jobPublishId": 155541019, "posName": "助理研究员岗", "_job_type": "校招",
            "_detail": {"posName": "助理研究员岗",
                        "responsibilities": "为各类投资组合提供研究支持。",
                        "qualifications": "境内外院校本科及以上学历。",
                        "requirements": "经济学类、金融学类相关专业。",
                        "phone": "hr@abc-ca.com"},
        }]}
        job = AbchinaAdapter().parse(json.dumps(payload, ensure_ascii=False))[0]

        self.assertIn("主要职责", job.summary)
        self.assertIn("为各类投资组合提供研究支持。", job.summary)
        self.assertIn("基本条件", job.summary)
        self.assertIn("具体要求", job.summary)
        # 薄卡门是 60 字：拼出来的正文必须真的过得去，否则补了等于没补。
        self.assertGreaterEqual(len(job.summary), 60)
        # ⚠️ posDetails.phone 是 HR 的联系方式，属于个人联系信息，不许进库（同 gree 的 PubName）。
        self.assertNotIn("hr@abc-ca.com", job.summary)

    def test_missing_sections_do_not_fabricate_a_summary(self):
        """快档（CRAWL_DETAIL_CAP=0）不跑详情 → 没有 _detail → summary 必须是 None，不许编。"""
        self.assertIsNone(AbchinaAdapter._summary_of({"posName": "软件研发岗"}))
        self.assertIsNone(AbchinaAdapter._summary_of({"_detail": {"phone": "hr@abc.com"}}))
        only_one = AbchinaAdapter._summary_of({"_detail": {"requirements": "计算机相关专业。"}})
        self.assertEqual(only_one, "具体要求\n计算机相关专业。")

    def test_is_not_in_the_httpx_concurrency_lane(self):
        # 它要起 Playwright（响应体加密，明文只在浏览器里），进并发档会把 sync API 跑崩。
        import sys, pathlib as _p
        sys.path.insert(0, str(_p.Path(__file__).resolve().parent))
        import run
        self.assertIn("abchina", run.ADAPTERS)
        self.assertIn("abchina", run.DOMESTIC_ADAPTERS)
        self.assertFalse(run._is_httpx_safe("abchina"))



class _DetailFakePage:
    """够用的 Playwright page 替身（只服务正文那一段）。

    ⚠️ 建模的是「**每次页面加载**内容固定」——不是「每次 evaluate 换一个答案」。
    _detail_of 在同一次加载里会反复轮询 evaluate，按调用次数发答案会让「重试了几次」这类
    断言静默失真。所以这里按 reload 代次取值。
    """

    def __init__(self, details_per_load=()):
        self.details_per_load = list(details_per_load)
        self.opens = 0

    def goto(self, url, **kw):
        pass

    def reload(self, **kw):
        self.opens += 1

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script, arg=None):
        if not self.details_per_load:
            return None
        return self.details_per_load[min(max(self.opens - 1, 0), len(self.details_per_load) - 1)]


class _FastAbchina(AbchinaAdapter):
    """轮询立刻到期，测试不去真的等 9 秒。
    ⚠️ 必须在**类**上覆盖：_collect 是 classmethod、读的是 cls.RENDER_TIMEOUT_MS，
    在实例上赋值不起作用。"""
    RENDER_TIMEOUT_MS = 0
    DETAIL_TIMEOUT_MS = 0


class _RecordingAbchina(_FastAbchina):
    """记下正文那一段问过哪些岗（把联网那一步换掉，只测 _fill_bodies 的调度逻辑）。"""

    def __init__(self):
        super().__init__()
        self.asked = []

    def _detail_of(self, page, job_id, want_name):
        self.asked.append(job_id)
        return {"posName": want_name, "responsibilities": "职责"}


class AbchinaBodyPassTest(unittest.TestCase):
    """逐岗正文：不补就是 100% 薄卡（线上实测 2,418 个岗 summary 全为 NULL），
    这家在必投健康覆盖里恒为 0。"""

    @staticmethod
    def _rows(n):
        return [{"jobPublishId": str(i), "posName": "岗%d" % i} for i in range(n)]

    def test_detail_belonging_to_another_job_is_refused(self):
        """详情页的 posName 与列表卡对不上就不要 —— 宁可留薄卡，也不能把 A 岗的正文挂到 B 岗。"""
        page = _DetailFakePage(details_per_load=[{"posName": "另一个岗", "responsibilities": "别人的职责"}])
        self.assertIsNone(_FastAbchina()._detail_of(page, "155541019", "助理研究员岗"))

    def test_detail_matching_the_card_is_accepted(self):
        page = _DetailFakePage(details_per_load=[{"posName": "助理研究员岗", "responsibilities": "研究支持"}])
        detail = _FastAbchina()._detail_of(page, "155541019", "助理研究员岗")
        self.assertEqual(detail["responsibilities"], "研究支持")

    def test_rotates_start_across_days_so_the_tail_is_not_starved(self):
        """预算/条数用完就停；若每晚都从第 0 个开始，后面的岗**永远**补不到正文。
        summary 在 upsert 里空值不覆盖，所以轮转几晚就能把全源覆盖一遍。"""
        seen = []
        for yday in (1, 2):
            adapter = _RecordingAbchina()
            with mock.patch.object(abchina.time, "gmtime",
                                   return_value=time.struct_time((2026, 1, 1, 0, 0, 0, 0, yday, 0))):
                adapter._fill_bodies(None, self._rows(7), cap=3)
            seen.append(adapter.asked)

        self.assertEqual([len(x) for x in seen], [3, 3])
        self.assertNotEqual(seen[0], seen[1], "两天起点相同 = 尾部岗位永远补不到正文")

    def test_wraps_around_instead_of_running_off_the_end(self):
        adapter = _RecordingAbchina()
        with mock.patch.object(abchina.time, "gmtime",
                               return_value=time.struct_time((2026, 1, 1, 0, 0, 0, 0, 1, 0))):
            adapter._fill_bodies(None, self._rows(7), cap=7)
        # 起点在中间也要覆盖全部 7 个，不能只补到末尾就停。
        self.assertEqual(sorted(adapter.asked, key=int), [str(i) for i in range(7)])

    def test_fast_lane_cap_zero_skips_the_body_pass_entirely(self):
        adapter = _RecordingAbchina()
        adapter._fill_bodies(None, self._rows(5), cap=0)
        self.assertEqual(adapter.asked, [])

    def test_body_pass_stops_after_a_run_of_failures(self):
        """站点掐连接时别把剩下两千多个岗每个都耗满两次 goto 超时。"""
        class _AlwaysMisses(_FastAbchina):
            def __init__(self):
                super().__init__()
                self.tries = 0

            def _detail_of(self, page, job_id, want_name):
                self.tries += 1
                return None

        adapter = _AlwaysMisses()
        adapter._fill_bodies(None, self._rows(500), cap=500)
        self.assertEqual(adapter.tries, AbchinaAdapter._DETAIL_ABORT_AFTER_FAILURES)

    def test_body_pass_runs_after_the_list_retry_round(self):
        """正文是锦上添花，绝不能挤掉列表的完整性 —— 调用点必须在重试轮之后。"""
        src = (pathlib.Path(__file__).resolve().parent / "adapters" / "abchina.py").read_text(encoding="utf-8")
        self.assertLess(src.index("for recruit_type, job_type, org in list(pending):"),
                        src.index("self._fill_bodies(page, rows,"))


if __name__ == "__main__":
    unittest.main()
