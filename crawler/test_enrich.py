"""enrich.py 富化注册表 + enrich_backlog drain 的单测（纯函数 / mock，不打真网络）。

重点：
  1. 每个 httpx fetcher 把 jd_url 正确反推成 detail 端点（错了 = 静默灌错 summary，最危险）。
  2. ENRICH_REGISTRY 分发 + detail_class 分流。
  3. drain 死信：富化无果 → enrich_fail_count+1，不动 summary；有果 → 只写 summary。
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import enrich
import enrich_backlog


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class HotjobDetailTest(unittest.TestCase):
    def test_reverses_jd_url_to_detail_post(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SU123/pb/posDetail.html?postId=P9&postType=campus",
               "title": "算法工程师"}
        src = {"source_url": "https://wecruit.hotjob.cn/SU123/pb/school.html", "adapter_name": "hotjob"}
        cap = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            cap["url"] = url
            cap["data"] = data
            return _Resp({"data": {"workContent": "负责算法", "serviceCondition": "本科以上"}})

        with mock.patch.object(enrich.httpx, "post", fake_post):
            body = enrich.ENRICH_REGISTRY["hotjob"](row, src)
        self.assertIn("/wecruit/positionInfo/listPositionDetail/SU123", cap["url"])
        self.assertEqual(cap["data"]["postId"], "P9")
        self.assertEqual(cap["data"]["recruitType"], 1)  # campus → 1
        self.assertIn("负责算法", body)
        self.assertIn("本科以上", body)

    def test_society_maps_recruit_type_2(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SUx/pb/posDetail.html?postId=1&postType=society"}
        src = {"source_url": "https://wecruit.hotjob.cn/SUx/pb/social.html", "adapter_name": "hotjob"}
        cap = {}
        with mock.patch.object(enrich.httpx, "post",
                               lambda url, data=None, headers=None, timeout=None: cap.update(d=data) or _Resp({"data": {}})):
            enrich.ENRICH_REGISTRY["hotjob"](row, src)
        self.assertEqual(cap["d"]["recruitType"], 2)

    def test_missing_postid_returns_empty(self):
        row = {"jd_url": "https://wecruit.hotjob.cn/SUx/pb/posDetail.html"}
        src = {"source_url": "https://wecruit.hotjob.cn/SUx/pb/social.html", "adapter_name": "hotjob"}
        self.assertEqual(enrich.ENRICH_REGISTRY["hotjob"](row, src), "")

    def test_closed_signal_raises_jobclosed(self):
        # 源站已撤岗：HTTP 200 + {"state":"1017","msg":"...已经关闭..."}，无 data/workContent。
        # 必须区别于「无正文」(返回"")——这是 expired 信号，不是死信。
        row = {"jd_url": "https://wecruit.hotjob.cn/SU1/pb/posDetail.html?postId=P1&postType=society"}
        src = {"source_url": "https://wecruit.hotjob.cn/SU1/pb/social.html", "adapter_name": "hotjob"}
        closed = {"msg": "该职位招聘已经关闭，请查看其他职位", "state": "1017", "type": "warning"}
        with mock.patch.object(enrich.httpx, "post",
                               lambda url, data=None, headers=None, timeout=None: _Resp(closed)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["hotjob"](row, src)


class WtDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://feihe.hotjob.cn/wt/feihe/mobweb/position/detail"
                      "?brandCode=1&safe=Y&recruitType=1&postIdsAry=153001"}
    _SRC = {"source_url": "https://feihe.hotjob.cn/wt/feihe/web/index", "adapter_name": "wt"}

    def test_reverses_to_json_detail_and_extracts_summary(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            cap["params"] = params
            return _Resp({"req_state": 9200,
                          "postInfo": {"workContent": "负责生产实训", "serviceCondition": "本科以上学历"}})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)
        self.assertEqual(cap["url"], "https://feihe.hotjob.cn/wt/feihe/web/json/position/detail")
        self.assertEqual(cap["params"]["postId"], "153001")
        self.assertEqual(str(cap["params"]["recruitType"]), "1")
        self.assertIn("负责生产实训", body)
        self.assertIn("本科以上学历", body)

    def test_closed_req_state_9501_raises_jobclosed(self):
        # 源站撤岗：HTTP 200 + {"req_state":9501,"req_msg":"…招聘已经关闭…"}，无 postInfo。
        closed = {"req_state": 9501, "req_msg": "该职位招聘已经关闭，请关注其他职位，谢谢!"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(closed)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["wt"](self._ROW, self._SRC), "")

    def test_missing_postid_returns_empty(self):
        row = {"jd_url": "https://feihe.hotjob.cn/wt/feihe/mobweb/position/detail?recruitType=1"}
        self.assertEqual(enrich.ENRICH_REGISTRY["wt"](row, self._SRC), "")


class WorkdayDetailTest(unittest.TestCase):
    def test_reverses_to_cxs_endpoint(self):
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Beijing/Eng_R-1"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs", "adapter_name": "workday"}
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"jobPostingInfo": {"jobDescription": "<p>do things</p>"}})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["workday"](row, src)
        self.assertEqual(cap["url"], "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/job/Beijing/Eng_R-1")
        self.assertIn("do things", body)

    def test_404_raises_jobclosed(self):
        # Workday cxs：岗位下架后 /job/{path} 返回 404 = 撤岗信号 → expired（≠ 无正文）。
        row = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/X/R-2"}
        src = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["workday"](row, src)

    _ROW = {"jd_url": "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/X/R-2"}
    _SRC = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs",
            "adapter_name": "workday"}

    def test_non_2xx_raises_unknown_not_closed(self):
        # 非 2xx（404/410 除外）= 没探到：429 是 Workday 按 IP 限流，422 是租户搬了数据中心
        # （武田 wd3→wd502 后旧地址每个岗都回 422），5xx 是瞬时错误。
        # 不能 expired（误杀在招岗），也不能 return ""——空串会被当成「确认在招」盖戳（F3）。
        for status in (401, 403, 422, 429, 500, 503):
            with self.subTest(status=status), \
                    mock.patch.object(enrich.httpx, "get", lambda *a, _s=status, **k: _Resp({}, status=_s)):
                with self.assertRaises(enrich.DetailUnknownError):
                    enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC)

    def test_2xx_without_description_still_returns_empty(self):
        # 2xx 是可判读的答复：岗位还在、只是没正文 → 仍返回 ""（巡检照常盖戳）。
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({"jobPostingInfo": {}})):
            self.assertEqual(enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC), "")

    def test_unknown_does_not_stamp_row_as_alive(self):
        # 端到端：已有正文的岗被限流 → enrich_row 记 err、不写库（不盖 enrich_checked_at，下轮重试）。
        row = {"id": "job-1", "source_id": "src-1", "title": "t", "jd_url": self._ROW["jd_url"],
               "job_type": None, "summary": "旧正文", "enrich_fail_count": 0}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=429)), \
                mock.patch.object(enrich_backlog.jobs_db, "execute") as ex:
            res = enrich_backlog.enrich_row(None, row, self._SRC, dry_run=False, jobs_conn=object())
        self.assertEqual(res, "err")
        ex.assert_not_called()

    def test_403_s22_raises_jobclosed(self):
        # Workday 撤岗大多不是 404，是 403 + {"errorCode":"S22"}（2026-09-23 live：该岗已不在对方公开列表、
        # 公开页渲染「The page you are looking for doesn't exist.」）。
        body = {"errorCode": "S22", "message": "permission denied", "httpStatus": 403}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(body, status=403)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC)

    def test_403_without_s22_is_not_closed(self):
        # 双条件：只有 403 且 errorCode=S22 才判死。别的 403（WAF / 其它错误码）不判死，记「没探到」。
        for body in ({}, {"errorCode": "S21"}, {"message": "permission denied"}):
            with self.subTest(body=body), \
                    mock.patch.object(enrich.httpx, "get", lambda *a, _b=body, **k: _Resp(_b, status=403)):
                with self.assertRaises(enrich.DetailUnknownError):
                    enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC)

    def test_s22_with_other_status_is_not_closed(self):
        body = {"errorCode": "S22"}
        # 2xx 带 S22 字样：可判读的答复、没正文 → ""（不判死）。
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(body, status=200)):
            self.assertEqual(enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC), "")
        # 非 403 的错误码带 S22：不判死，记「没探到」。
        for status in (401, 422, 429, 500):
            with self.subTest(status=status), \
                    mock.patch.object(enrich.httpx, "get", lambda *a, _s=status, **k: _Resp(body, status=_s)):
                with self.assertRaises(enrich.DetailUnknownError):
                    enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC)

    def test_expire_guard_lets_backlog_through_but_trips_on_signal_flip(self):
        # 上线清存量那几轮：按真实队列顺序（source_id 排序 + 每轮 5 万 + 按源交错）重放全量 dry-run，
        # 累计判死占比最高 59.6% —— 阈值必须高于它，否则存量永远清不掉（照抄北森的 0.5 会卡死）。
        self.assertFalse(enrich_backlog.should_trip_expire_guard("workday", 25525, 15215))  # 59.6%
        self.assertFalse(enrich_backlog.should_trip_expire_guard("workday", 50000, 28789))  # 57.6%
        # S22 语义哪天被 Workday 挪作他用 → 几乎全判死，200 个样本内就停。
        self.assertTrue(enrich_backlog.should_trip_expire_guard("workday", 200, 200))
        self.assertTrue(enrich_backlog.should_trip_expire_guard("workday", 1000, 800))

    def test_403_non_json_body_is_not_closed(self):
        # CDN/WAF 拦截回的是 HTML 403，不是 Workday 应用层的 S22 → 不许判死。
        class _Html(_Resp):
            def json(self):
                raise ValueError("not json")
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Html(None, status=403)):
            with self.assertRaises(enrich.DetailUnknownError):
                enrich.ENRICH_REGISTRY["workday"](self._ROW, self._SRC)


class WorkdayPostingMovedTest(unittest.TestCase):
    """Workday 只按链接最后一段找帖子：对方改了主地点，链接的地点段跟着变，旧链接照样回 200。
    探活器要把「还在招、但现在不是这个链接」报出来（2026-10-14）。"""
    _OLD = "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Singapore/Eng_R-1"
    _SRC = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs", "adapter_name": "workday"}

    def _probe(self, external, location="Taipei, Taiwan", alpha2="TW"):
        info = {"jobPostingInfo": {"externalUrl": external, "location": location, "jobDescription": "<p>do things</p>",
                                   "jobRequisitionLocation": {"country": {"alpha2Code": alpha2}}}}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(info)):
            return enrich.ENRICH_REGISTRY["workday"]({"jd_url": self._OLD}, self._SRC)

    def test_same_link_is_not_moved(self):
        # externalUrl 不带 locale、站点名大小写不同：还是这一条链接
        self.assertIn("do things", self._probe("https://co.wd1.myworkdayjobs.com/careers/job/Singapore/Eng_R-1"))

    def test_changed_location_segment_raises_moved_with_db_style_url(self):
        with self.assertRaises(enrich.PostingMovedError) as cm:
            self._probe("https://co.wd1.myworkdayjobs.com/Careers/job/Taipei/Eng_R-1")
        e = cm.exception
        # 新链接按库里那条的写法拼（保留 /en-US/ 与站点名原样）：列表日后给出它时 canonical 对得上
        self.assertEqual(e.new_url, "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Taipei/Eng_R-1")
        self.assertEqual((e.location, e.country_code), ("Taipei, Taiwan", "TW"))
        self.assertIn("do things", e.body)

    def test_moved_location_is_cleaned_like_the_adapter(self):
        # 报出来的地点过 adapter 写库前同一道清洗（「 - 」换逗号、CHN 展开），巡检换链接时写的和下一轮列表写的是同一个值
        with self.assertRaises(enrich.PostingMovedError) as cm:
            self._probe("https://co.wd1.myworkdayjobs.com/Careers/job/CHN---Beijing/Eng_R-1",
                        location="CHN - Beijing - Beijing (Wangjing Park)", alpha2="CN")
        self.assertEqual(cm.exception.location, "China, Beijing, Beijing (Wangjing Park)")

    def test_myworkdaysite_external_url_is_the_same_posting(self):
        # 富达 / 麦格纳 / 富国 / 亿滋的 externalUrl 是 wdN.myworkdaysite.com/recruiting/{租户}/{站点}/… 这种写法
        with self.assertRaises(enrich.PostingMovedError) as cm:
            self._probe("https://wd1.myworkdaysite.com/recruiting/co/Careers/job/Durham-NC/Eng_R-1")
        self.assertEqual(cm.exception.new_url, "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Durham-NC/Eng_R-1")

    def test_other_posting_is_not_moved(self):
        # 末尾多一个 -1 是同一个编号下的另一个帖子；别家租户 / 别的站点 / 没给链接：都不认成同一个帖子
        for ext in ("https://co.wd1.myworkdayjobs.com/Careers/job/Taipei/Eng_R-1-1",
                    "https://other.wd1.myworkdayjobs.com/Careers/job/Taipei/Eng_R-1",
                    "https://co.wd1.myworkdayjobs.com/Other/job/Taipei/Eng_R-1",
                    None, ""):
            with self.subTest(ext=ext):
                self.assertIn("do things", self._probe(ext))

    def test_slug_differing_only_in_case_or_encoding_is_not_moved(self):
        # 认错了会把链接换成列表永远不给的写法：只差大小写 / 百分号编码、带查询串或尾斜杠都算同一条
        for ext in ("https://co.wd1.myworkdayjobs.com/Careers/job/SINGAPORE/Eng_R-1",
                    "https://co.wd1.myworkdayjobs.com/Careers/job/Sing%61pore/Eng_R-1",
                    "https://co.wd1.myworkdayjobs.com/Careers/job/Singapore/Eng_R-1/?source=x"):
            with self.subTest(ext=ext):
                self.assertIn("do things", self._probe(ext))

    def test_moved_url_keeps_each_stored_link_shape(self):
        ext = "https://co.wd1.myworkdayjobs.com/Careers/job/Taipei/Eng_R-1?q=1"
        # 库里没有 locale（腾讯给的 PostURL 就是这样）/ 没有地点段 / 站点名恰好叫 job
        self.assertEqual(enrich._workday_moved_url("https://co.wd1.myworkdayjobs.com/Careers/job/Singapore/Eng_R-1", ext),
                         "https://co.wd1.myworkdayjobs.com/Careers/job/Taipei/Eng_R-1")
        self.assertEqual(enrich._workday_moved_url("https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Eng_R-1", ext),
                         "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Taipei/Eng_R-1")
        self.assertEqual(enrich._workday_moved_url("https://co.wd1.myworkdayjobs.com/en-US/job/job/Singapore/Eng_R-1",
                                                   "https://co.wd1.myworkdayjobs.com/job/job/Taipei/Eng_R-1"),
                         "https://co.wd1.myworkdayjobs.com/en-US/job/job/Taipei/Eng_R-1")
        # 库里那条是 myworkdaysite 写法：不替它改写
        self.assertIsNone(enrich._workday_moved_url(
            "https://wd1.myworkdaysite.com/recruiting/co/Careers/job/Singapore/Eng_R-1", ext))


class TencentWorkdayLinkTest(unittest.TestCase):
    """腾讯海外岗的 PostURL 是 Workday 链接、没有 postId：以前直接 return ""，有正文的行被巡检盖「在招」章、永远判不死
    （2026-10-14 全量：323 行超过 30 小时没被列表看到，310 行 Workday 回 403 S22）。"""
    _SRC = {"source_url": "https://careers.tencent.com/", "adapter_name": "tencent"}

    def test_workday_link_asks_workday_detail(self):
        row = {"jd_url": "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Malaysia-Kuala-Lumpur/Architect_R107538-1"}
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"errorCode": "S22", "message": "permission denied"}, status=403)

        with mock.patch.object(enrich.httpx, "get", fake_get):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["tencent"](row, self._SRC)
        self.assertEqual(cap["url"], "https://tencent.wd1.myworkdayjobs.com/wday/cxs/tencent/Tencent_Careers"
                                     "/job/Malaysia-Kuala-Lumpur/Architect_R107538-1")

    def test_workday_link_moved_is_reported(self):
        row = {"jd_url": "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/Singapore/Architect_R107538-1"}
        info = {"jobPostingInfo": {"externalUrl": "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/"
                                                  "Malaysia-Kuala-Lumpur/Architect_R107538-1",
                                   "location": "Malaysia, Kuala Lumpur", "jobDescription": "<p>x</p>"}}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp(info)):
            with self.assertRaises(enrich.PostingMovedError) as cm:
                enrich.ENRICH_REGISTRY["tencent"](row, self._SRC)
        self.assertEqual(cm.exception.new_url, "https://tencent.wd1.myworkdayjobs.com/Tencent_Careers/job/"
                                               "Malaysia-Kuala-Lumpur/Architect_R107538-1")

    def test_postid_link_still_asks_tencent(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"], cap["params"] = url, params
            return _Resp({"Code": 200, "Data": {"Responsibility": "负责后端", "Requirement": "三年经验"}})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["tencent"]({"jd_url": "https://careers.tencent.com/jobdesc.html?postId=123"},
                                                    self._SRC)
        self.assertEqual((cap["url"], cap["params"]),
                         ("https://careers.tencent.com/tencentcareer/api/post/ByPostId", {"postId": "123"}))
        self.assertIn("负责后端", body)


class SettleMovedPostingTest(unittest.TestCase):
    """巡检拿到「帖子挪了」之后的处置（enrich_backlog._settle_moved）。只在「旧链接 30 小时没被列表看到」且
    「库里没有新链接的在招行」时动手：新链接已有在招行是写库端认旧链接的活，这里不抢。"""
    _SRC = {"source_url": "https://co.wd1.myworkdayjobs.com/wday/cxs/co/Careers/jobs", "adapter_name": "workday",
            "company": "Co", "regions": ["CN", "US", "SG", "Remote"]}
    _OLD = "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Singapore/Eng_R-1"
    _NEW = "https://co.wd1.myworkdayjobs.com/en-US/Careers/job/Shanghai/Eng_R-1"

    def _row(self, hours_ago=40, summary="旧正文"):
        return {"id": "job-1", "source_id": "src-1", "title": "Engineer", "jd_url": self._OLD, "job_type": None,
                "summary": summary, "enrich_fail_count": 0,
                "last_seen_at": datetime.now(timezone.utc) - timedelta(hours=hours_ago)}

    def _run(self, row=None, location="Shanghai", country="CN", statuses=(), src=None, dry_run=False,
             jobs_conn="conn", write_error=None, updated_rows=1):
        moved = enrich.PostingMovedError(self._NEW, location, country, "<p>还在招的正文</p>")
        writes = []

        def fake_one(a, r, s):
            raise moved

        def fake_execute(conn, sql, params=None):
            if write_error:
                raise write_error
            writes.append((sql, list(params or [])))
            return updated_rows

        sb = _FakeSB()
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", fake_one), \
                mock.patch.object(enrich_backlog.jobs_db, "fetch_all",
                                  lambda conn, sql, params=None: [{"status": s} for s in statuses]), \
                mock.patch.object(enrich_backlog.jobs_db, "execute", fake_execute):
            res = enrich_backlog.enrich_row(sb, row or self._row(), src or self._SRC, dry_run=dry_run,
                                            jobs_conn=jobs_conn)
        return res, writes, sb

    @staticmethod
    def _patch_of(write):
        sql, params = write
        cols = [c.split(" = ")[0] for c in sql.split(" set ", 1)[1].split(" where ")[0].split(", ")]
        return dict(zip(cols, params)), sql, params[len(cols):]

    def test_in_region_relinks_in_place_and_stays_active(self):
        res, writes, _ = self._run()
        self.assertEqual(res, "relinked")
        patch, sql, where = self._patch_of(writes[0])
        self.assertEqual((patch["jd_url"], patch["apply_url"]), (self._NEW, self._NEW))
        self.assertEqual((patch["location"], patch["country_code"], patch["job_scope"]), ("上海", "CN", "domestic"))
        self.assertNotIn("status", patch)
        self.assertNotIn("summary", patch)  # 已有正文不重写
        self.assertIn("enrich_checked_at", patch)
        # 只动「还在招、还是旧链接、此刻仍 30 小时没被看到」的那一行：队列取完之后被别人动过就不换
        self.assertIn("status = 'active' and jd_url = %s and last_seen_at < now()", sql)
        self.assertEqual(where, ["job-1", self._OLD, enrich_backlog.MOVED_STALE_HOURS])

    def test_relink_fills_missing_summary(self):
        res, writes, _ = self._run(row=self._row(summary=None))
        self.assertEqual(res, "relinked")
        self.assertIn("还在招的正文", self._patch_of(writes[0])[0]["summary"])

    def test_out_of_region_is_removed_and_relinked(self):
        # 新地点不在本源地区内（马来西亚 / 台湾）：我们现在不收它 → removed；链接顺手换成新的，
        # 日后列表又给出它时写库按 canonical 认到这一行，原 id 复活
        for loc, cc in (("Kuala Lumpur, Malaysia", "MY"), ("Taipei, Taiwan", "TW")):
            with self.subTest(loc=loc):
                res, writes, _ = self._run(location=loc, country=cc)
                self.assertEqual(res, "removed")
                patch = self._patch_of(writes[0])[0]
                self.assertEqual(patch["status"], "removed")
                self.assertEqual((patch["jd_url"], patch["apply_url"]), (self._NEW, self._NEW))
                self.assertNotIn("location", patch)

    def test_removed_keeps_link_when_new_link_already_has_an_inactive_row(self):
        res, writes, _ = self._run(location="Kuala Lumpur, Malaysia", country="MY", statuses=("removed",))
        self.assertEqual(res, "removed")
        patch = self._patch_of(writes[0])[0]
        self.assertEqual(patch["status"], "removed")
        self.assertNotIn("jd_url", patch)  # 不再造第二行占着同一个链接

    def test_new_link_already_active_is_left_to_the_writer(self):
        # 列表已经给了新链接（库里有它的在招行）→ 写库端会下架旧行并把最早首见记到新行上，这里只照常盖戳
        res, writes, _ = self._run(location="Kuala Lumpur, Malaysia", country="MY", statuses=("active",))
        self.assertEqual(res, "alive")
        patch, _sql, where = self._patch_of(writes[0])
        self.assertEqual(list(patch), ["enrich_checked_at"])
        self.assertEqual(where, ["job-1"])

    def test_recently_listed_row_is_not_touched(self):
        # 旧链接 30 小时内还被列表看到：对方刚改、列表还没来得及给新链接 → 不动，留给下一轮列表
        res, writes, _ = self._run(row=self._row(hours_ago=5), location="Kuala Lumpur, Malaysia", country="MY")
        self.assertEqual(res, "alive")
        self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])

    def test_unknown_last_seen_or_no_jobs_db_is_not_touched(self):
        row = self._row()
        row["last_seen_at"] = None
        res, writes, _ = self._run(row=row, location="Kuala Lumpur, Malaysia", country="MY")
        self.assertEqual(res, "alive")
        self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])
        # Supabase 兜底路径（没配香港库）不处置，照常当在招
        res, writes, sb = self._run(location="Kuala Lumpur, Malaysia", country="MY", jobs_conn=None)
        self.assertEqual((res, writes), ("alive", []))
        self.assertEqual(list(sb.updates["job-1"]), ["enrich_checked_at"])

    def test_tencent_moved_and_unlisted_is_removed_even_in_region(self):
        # 腾讯那条源不按地区筛：挪了且两个链接都不在列表里 = 已不在腾讯的公开列表上
        src = {"source_url": "https://careers.tencent.com/", "adapter_name": "tencent", "company": "腾讯",
               "regions": ["CN"]}
        res, writes, _ = self._run(src=src)
        self.assertEqual(res, "removed")
        self.assertEqual(self._patch_of(writes[0])[0]["status"], "removed")

    def test_dry_run_does_not_write(self):
        res, writes, _ = self._run(dry_run=True)
        self.assertEqual((res, writes), ("relinked", []))

    def test_unclear_location_is_not_touched(self):
        # 宁可漏判：地点说不清国家（空 / 光写城市名 / 门牌地址）且对方没自报国家 → 不动，照常当在招
        for loc, cc in ((None, None), ("", None), ("Frederick", None), ("LOC6035: Rua 680", None),
                        ("Kuala Lumpur, Malaysia", None),
                        (None, "US"), ("", "DE")):  # 没给主地点：换链接会把地点写空，自报国家也不用
            with self.subTest(loc=loc, cc=cc):
                res, writes, _ = self._run(location=loc, country=cc)
                self.assertEqual(res, "alive")
                self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])

    def test_unclear_location_uses_declared_country(self):
        # geo 只认得少数国家（「Kuala Lumpur, Malaysia」它也说不清），说不清时看 Workday 自报的国家
        res, writes, _ = self._run(location="Lynnfield MA Branch", country="US")
        self.assertEqual(res, "relinked")
        patch = self._patch_of(writes[0])[0]
        self.assertEqual((patch["jd_url"], patch["country_code"]), (self._NEW, "US"))
        res, writes, _ = self._run(location="Kuala Lumpur, Malaysia", country="MY")
        self.assertEqual((res, self._patch_of(writes[0])[0]["status"]), ("removed", "removed"))

    def test_location_and_declared_country_disagree_is_not_touched(self):
        # 只抓国内的源：主地点新加坡（地点自己说得清、不在范围内），附加地点上海（自报国家折成 CN）
        # → 列表的中国分组多半还收它，两边打架 → 不动
        src = dict(self._SRC, regions=["CN"])
        res, writes, _ = self._run(location="Singapore", country="CN", src=src)
        self.assertEqual(res, "alive")
        self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])

    def test_in_region_does_not_relink_onto_a_link_another_row_holds(self):
        # 新链接上有一行下架 / 撤岗过的：换过去会撞「公司+标题+地点+链接」不分状态的唯一约束 → 不动
        res, writes, _ = self._run(statuses=("removed",))
        self.assertEqual(res, "alive")
        self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])

    def test_write_failure_falls_back_to_alive_stamp(self):
        # 另一轮抓取刚把新链接插成在招行 → 换链接撞唯一索引：这一轮照常盖在招章，下一轮归写库端
        writes = []

        def fake_execute(conn, sql, params=None):
            if "jd_url = %s, apply_url" in sql:
                raise RuntimeError("duplicate key value violates unique constraint")
            writes.append((sql, list(params or [])))
            return 1

        moved = enrich.PostingMovedError(self._NEW, "Shanghai", "CN", "<p>正文</p>")
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", mock.Mock(side_effect=moved)), \
                mock.patch.object(enrich_backlog.jobs_db, "fetch_all", lambda *a, **k: []), \
                mock.patch.object(enrich_backlog.jobs_db, "execute", fake_execute):
            res = enrich_backlog.enrich_row(None, self._row(), self._SRC, jobs_conn="conn")
        self.assertEqual(res, "alive")
        self.assertEqual(list(self._patch_of(writes[0])[0]), ["enrich_checked_at"])

    def test_row_changed_meanwhile_falls_back(self):
        # 查完之后这一行被别人动过（换了链接 / 下架了）：update 命中 0 行 → 不算处置
        res, writes, _ = self._run(updated_rows=0)
        self.assertEqual(res, "alive")

    def test_settle_error_never_escapes(self):
        with mock.patch.object(enrich_backlog, "_settle_moved", mock.Mock(side_effect=TypeError("boom"))):
            res, _writes, _ = self._run()
        self.assertEqual(res, "alive")

    def test_guard_counts_moved_rows(self):
        # externalUrl 的写法哪天变了，每个岗都会被认成「挪了」：下架 / 换链接都算进熔断分子
        for verdict in ("removed", "relinked"):
            with self.subTest(verdict=verdict):
                rows = [{"id": f"j{i}", "source_id": f"s{i % 10}", "jd_url": "u"} for i in range(500)]
                smap = {f"s{i}": {"adapter_name": "workday", "company": "Co",
                                  "source_url": f"https://t{i}.wd1.myworkdayjobs.com/wday/cxs/t/S/jobs"} for i in range(10)}
                with mock.patch.object(enrich_backlog, "fetch_liveness_queue", lambda *a, **k: (rows, smap)), \
                        mock.patch.object(enrich_backlog.jobs_db, "enabled", lambda: False), \
                        mock.patch.object(enrich_backlog.must_apply, "patterns", lambda: []), \
                        mock.patch.object(enrich_backlog, "enrich_row", lambda *a, **k: verdict):
                    stat = enrich_backlog.drain(None, adapter="workday", workers=1, dry_run=True, sweep=True,
                                                make_sb=lambda: None)
                self.assertEqual(stat[verdict], enrich_backlog.EXPIRE_GUARD_MIN_SAMPLE)
                self.assertEqual(stat["skipped"], 500 - enrich_backlog.EXPIRE_GUARD_MIN_SAMPLE)

    def test_last_seen_must_be_a_datetime(self):
        # 香港库给带时区的 datetime；Supabase 兜底路径本来就不处置（没有 jobs_conn），字符串一律当没有
        self.assertEqual(enrich_backlog._as_utc(datetime(2026, 10, 14, 1, 2, 3)),
                         datetime(2026, 10, 14, 1, 2, 3, tzinfo=timezone.utc))
        self.assertIsNone(enrich_backlog._as_utc("2026-10-14T01:02:03Z"))


class OracleDetailTest(unittest.TestCase):
    _JD = "https://co.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/12345"

    def test_reverses_to_rest_endpoint(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"items": [{"ExternalDescriptionStr": "做 oracle 的事"}]})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["oracle"](row, src)
        self.assertIn("recruitingCEJobRequisitionDetails", cap["url"])
        self.assertIn('Id="12345"', cap["url"])
        self.assertIn("siteNumber=CX_1", cap["url"])
        self.assertIn("做 oracle 的事", body)

    def test_empty_items_raises_jobclosed(self):
        # finder by Id 返回 HTTP 200 + items:[] = 该 requisition 已撤 → expired。
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({"items": []})):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["oracle"](row, src)

    def test_404_raises_jobclosed(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["oracle"](row, src)

    def test_transient_5xx_returns_empty_not_closed(self):
        row = {"jd_url": self._JD}
        src = {"source_url": "x", "adapter_name": "oracle"}
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["oracle"](row, src), "")

    def test_unmatched_jd_url_returns_empty_not_closed(self):
        # jd_url 反推不出 site/job（解析失败）→ 返回 ""（miss），不得当撤岗 expired。
        row = {"jd_url": "https://co.fa.us2.oraclecloud.com/some/other/path"}
        src = {"source_url": "x", "adapter_name": "oracle"}
        self.assertEqual(enrich.ENRICH_REGISTRY["oracle"](row, src), "")


class EightfoldDetailTest(unittest.TestCase):
    _JD = "https://acme.com/careers/job/123456789"
    _SRC = {"source_url": "https://acme.eightfold.ai/api/apply/v2/jobs?domain=acme.com",
            "adapter_name": "eightfold"}

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["eightfold"]({"jd_url": self._JD}, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=502)):
            self.assertEqual(enrich.ENRICH_REGISTRY["eightfold"]({"jd_url": self._JD}, self._SRC), "")


class SmartRecruitersDetailTest(unittest.TestCase):
    _JD = "https://jobs.smartrecruiters.com/Acme/123456"
    _SRC = {"source_url": "x", "adapter_name": "smartrecruiters"}

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["smartrecruiters"]({"jd_url": self._JD}, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["smartrecruiters"]({"jd_url": self._JD}, self._SRC), "")


class GreenhouseDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://boards.greenhouse.io/acme/jobs/4567890"}
    _SRC = {"source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true",
            "adapter_name": "greenhouse"}

    def test_reverses_to_boards_api(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"content": "&lt;p&gt;Build things&lt;/p&gt;"})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC)
        self.assertEqual(cap["url"], "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4567890")
        self.assertIn("Build things", body)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=503)):
            self.assertEqual(enrich.ENRICH_REGISTRY["greenhouse"](self._ROW, self._SRC), "")


class LeverDetailTest(unittest.TestCase):
    _ROW = {"jd_url": "https://jobs.lever.co/acme/a1b2c3d4-1111-2222-3333-444455556666"}
    _SRC = {"source_url": "https://api.lever.co/v0/postings/acme?mode=json", "adapter_name": "lever"}

    def test_reverses_to_postings_api(self):
        cap = {}

        def fake_get(url, headers=None, timeout=None, params=None):
            cap["url"] = url
            return _Resp({"description": "<p>do work</p>",
                          "lists": [{"text": "Reqs", "content": "<li>python</li>"}],
                          "additional": "<p>perks</p>"})

        with mock.patch.object(enrich.httpx, "get", fake_get):
            body = enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC)
        self.assertEqual(cap["url"],
                         "https://api.lever.co/v0/postings/acme/a1b2c3d4-1111-2222-3333-444455556666")
        self.assertIn("do work", body)
        self.assertIn("python", body)

    def test_404_raises_jobclosed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC)

    def test_transient_5xx_returns_empty_not_closed(self):
        with mock.patch.object(enrich.httpx, "get", lambda *a, **k: _Resp({}, status=502)):
            self.assertEqual(enrich.ENRICH_REGISTRY["lever"](self._ROW, self._SRC), "")


class GoneHelperTest(unittest.TestCase):
    """通用撤岗约定：任何 fetcher 的 detail 端点 404/410 都判撤岗（杜绝逐源遗漏）。"""
    def test_raise_if_gone_404_410(self):
        for code in (404, 410):
            with self.assertRaises(enrich.JobClosedError):
                enrich._raise_if_gone(_Resp({}, status=code))

    def test_raise_if_gone_passes_through_others(self):
        for code in (200, 429, 500, 502, 503):
            enrich._raise_if_gone(_Resp({}, status=code))  # 不抛 = 通过


class RegistryTest(unittest.TestCase):
    def test_httpx_adapters_registered(self):
        for a in ("workday", "oracle", "eightfold", "smartrecruiters", "hotjob", "wt"):
            self.assertIn(a, enrich.ENRICH_REGISTRY)

    def test_detail_class(self):
        self.assertEqual(enrich.detail_class("hotjob"), "httpx")
        self.assertEqual(enrich.detail_class("wt"), "httpx")
        self.assertEqual(enrich.detail_class("workday"), "httpx")
        self.assertEqual(enrich.detail_class("moka"), "browser")
        self.assertEqual(enrich.detail_class("beisen"), "httpx")   # 2026-09-23 起有 httpx 探活器
        self.assertIsNone(enrich.detail_class("不存在的源"))

    def test_enrich_one_unknown_returns_empty(self):
        self.assertEqual(enrich.enrich_one("不存在", {"jd_url": "x"}, {}), "")


class _FakeSB:
    """记录 jobs.update 的 patch（按 id）。"""
    def __init__(self):
        self.updates = {}

    def table(self, name):
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def eq(self, col, val):
        self._eq = (col, val)
        return self

    def execute(self):
        if getattr(self, "_eq", (None,))[0] == "id":
            self.updates[self._eq[1]] = self._patch
        return self


class DrainRowTest(unittest.TestCase):
    def test_success_writes_summary_not_failcount(self):
        sb = _FakeSB()
        row = {"id": "j1", "source_id": "s", "title": "后端", "jd_url": "u", "job_type": None, "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "负责后端服务的设计与开发，维护线上稳定性"):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "filled")
        patch = sb.updates["j1"]
        self.assertIn("summary", patch)
        self.assertNotIn("enrich_fail_count", patch)
        self.assertIn("enrich_checked_at", patch)

    def test_empty_body_increments_failcount(self):
        sb = _FakeSB()
        row = {"id": "j2", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 1}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: ""):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "miss")
        patch = sb.updates["j2"]
        self.assertEqual(patch["enrich_fail_count"], 2)  # 1 → 2
        self.assertNotIn("summary", patch)

    def test_fetch_exception_counts_as_miss(self):
        sb = _FakeSB()
        row = {"id": "j3", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}

        def boom(a, r, s):
            raise RuntimeError("network down")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", boom):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "miss")
        self.assertEqual(sb.updates["j3"]["enrich_fail_count"], 1)

    def test_write_failure_returns_err_not_raise(self):
        # Errno35 等写库瞬时错误：enrich_row 返回 "err"（不抛），该行留队列下轮重试，不掀整批。
        class RaiseSB:
            def table(self, n): return self
            def update(self, p): return self
            def eq(self, c, v): return self
            def execute(self): raise RuntimeError("[Errno 35] Resource temporarily unavailable")
        row = {"id": "j5", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "足够长的真实职位描述正文内容"):
            res = enrich_backlog.enrich_row(RaiseSB(), row, src)
        self.assertEqual(res, "err")

    def test_closed_signal_sets_expired_not_failcount(self):
        # fetcher 报源站已关闭（JobClosedError）→ status='expired'，不当死信、不动 summary/fail_count。
        sb = _FakeSB()
        row = {"id": "j6", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 1}
        src = {"adapter_name": "hotjob", "source_url": "x"}

        def closed(a, r, s):
            raise enrich.JobClosedError("hotjob state=1017")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", closed):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "expired")
        patch = sb.updates["j6"]
        self.assertEqual(patch["status"], "expired")
        self.assertNotIn("enrich_fail_count", patch)
        self.assertNotIn("summary", patch)
        self.assertIn("enrich_checked_at", patch)

    def test_sweep_alive_job_with_summary_only_bumps_checked_at(self):
        # 巡检：仍在招、已有正文 → 只更新 enrich_checked_at，不重写 summary、不计死信。
        sb = _FakeSB()
        row = {"id": "j7", "source_id": "s", "title": "x", "jd_url": "u",
               "summary": "已有的职位正文", "enrich_fail_count": 0}
        src = {"adapter_name": "wt", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "重新抓到的正文也够长足够"):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "alive")
        patch = sb.updates["j7"]
        self.assertEqual(list(patch.keys()), ["enrich_checked_at"])
        self.assertNotIn("summary", patch)
        self.assertNotIn("enrich_fail_count", patch)

    def test_sweep_closed_job_with_summary_expires(self):
        # 核心修复：已有正文但源站已撤岗的存量岗（fetch_queue 永远碰不到）→ 巡检置 expired。
        sb = _FakeSB()
        row = {"id": "j8", "source_id": "s", "title": "x", "jd_url": "u",
               "summary": "旧的职位正文", "enrich_fail_count": 0}
        src = {"adapter_name": "wt", "source_url": "x"}

        def closed(a, r, s):
            raise enrich.JobClosedError("wt req_state=9501")

        with mock.patch.object(enrich_backlog.enrich, "enrich_one", closed):
            res = enrich_backlog.enrich_row(sb, row, src)
        self.assertEqual(res, "expired")
        self.assertEqual(sb.updates["j8"]["status"], "expired")

    def test_dry_run_does_not_write(self):
        sb = _FakeSB()
        row = {"id": "j4", "source_id": "s", "title": "x", "jd_url": "u", "enrich_fail_count": 0}
        src = {"adapter_name": "hotjob", "source_url": "x"}
        with mock.patch.object(enrich_backlog.enrich, "enrich_one", lambda a, r, s: "一段足够长的真实职位描述正文内容"):
            enrich_backlog.enrich_row(sb, row, src, dry_run=True)
        self.assertEqual(sb.updates, {})


if __name__ == "__main__":
    unittest.main()


class _HtmlResp:
    """HTML 详情页响应（siemens/google 是 SSR 页面，走 r.text 不是 r.json()）。"""

    def __init__(self, text, status=200):
        self.text = text
        self.status_code = status


class SiemensDetailTest(unittest.TestCase):
    """Siemens 338 个在招岗此前 100% 是无正文薄卡（adapter 根本不在 ENRICH_REGISTRY）。
    正文在详情页 <main> 里（live 验证 7.6k 字符；<article> 只有元信息，别用）。"""

    def test_extracts_jd_body_from_main_only(self):
        html = ("<html><body><nav>Global navigation noise</nav>"
                "<main><h1>Embedded C Software Senior Engineer</h1>"
                "<p>Job ID 510965 We are looking for...</p></main>"
                "<footer>Imprint</footer></body></html>")
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html)):
            out = enrich._detail_siemens(
                {"jd_url": "https://jobs.siemens.com/en_US/externaljobs/JobDetail/510965"}, {})
        self.assertIn("Embedded C Software Senior Engineer", out)
        self.assertIn("510965", out)
        self.assertNotIn("Global navigation noise", out)  # <main> 外的噪音不得混进 summary
        self.assertNotIn("Imprint", out)

    def test_404_raises_job_closed(self):
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp("", 404)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_siemens(
                    {"jd_url": "https://jobs.siemens.com/en_US/externaljobs/JobDetail/1"}, {})


class GoogleDetailTest(unittest.TestCase):
    """Google 撤岗是**软 404**：HTTP 仍 200，只有 <main> 文案变成 Job not found
    （live 抽样 5 个库内 active 岗，2 个已是这个状态）。不按文案判死 → 死岗永不下架。"""

    def test_extracts_jd_body_for_live_job(self):
        html = ("<html><body><main><h2>Partner Solutions Engineer</h2>"
                "<p>Minimum qualifications: Bachelor's degree...</p></main></body></html>")
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html)):
            out = enrich._detail_google(
                {"jd_url": "https://www.google.com/about/careers/applications/jobs/results/123-x"}, {})
        self.assertIn("Partner Solutions Engineer", out)
        self.assertIn("Minimum qualifications", out)

    def test_soft_404_body_raises_job_closed(self):
        html = ("<html><body><main>Job not found.This job may have been taken down."
                "Search again</main></body></html>")
        with mock.patch.object(enrich.httpx, "get", return_value=_HtmlResp(html, 200)):
            with self.assertRaises(enrich.JobClosedError):
                enrich._detail_google(
                    {"jd_url": "https://www.google.com/about/careers/applications/jobs/results/456-y"}, {})


class SiemensGoogleRegistryTest(unittest.TestCase):
    def test_registered_as_httpx_enrichable(self):
        self.assertEqual(enrich.detail_class("siemens"), "httpx")
        self.assertEqual(enrich.detail_class("google"), "httpx")

    def test_microsoft_stays_liveness_only_but_registered(self):
        # MS 详情页是纯 SPA（3 个 detail 端点全 404、<main> 为空）→ 只探活不补正文，别误以为能富化正文。
        self.assertEqual(enrich.detail_class("microsoft"), "httpx")


class SiemensClosedDetectionTest(unittest.TestCase):
    """回归守卫：Siemens 撤岗是 403 + 错误页，不是 404。

    2026-07-28 实测 JobDetail/510194 → HTTP 403，<main> 只剩
    "An error has occurred Page not found Go to open jobs"。
    _raise_if_gone 只认 404/410 → 旧实现把 403 当普通失败吞掉返回 ""，岗位永远留在 active：
    库里 484 个 Siemens active 岗**全部**在 7 天内被探过、却一个都没下架过。
    """

    class _Resp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    _CLOSED = ("<html><body><main>An error has occurred Page not found "
               "Go to open jobs</main></body></html>")
    _LIVE = ("<html><body><main>Requirement Manager @Siemens Mobility KSA Job ID 509645 "
             "Posted since 14-Jun-2026 Organization Mobility " + "detail " * 200
             + "</main></body></html>")

    def _run(self, resp):
        orig = enrich.httpx.get
        enrich.httpx.get = lambda *a, **k: resp
        try:
            return enrich._detail_siemens(
                {"jd_url": "https://jobs.siemens.com/en_US/externaljobs/JobDetail/510194"}, {})
        finally:
            enrich.httpx.get = orig

    def test_403_error_page_marks_job_closed(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(self._Resp(403, self._CLOSED))

    def test_403_without_error_copy_is_not_closed(self):
        """光看 403 不够——可能是 WAF 临时拦截，误判会误杀活岗。"""
        blocked = "<html><body><main>Access denied by security policy</main></body></html>"
        self.assertEqual(self._run(self._Resp(403, blocked)), "")

    def test_live_job_still_returns_body(self):
        out = self._run(self._Resp(200, self._LIVE))
        self.assertIn("Requirement Manager", out)

    def test_404_still_closed_via_shared_gate(self):
        with self.assertRaises(enrich.JobClosedError):
            self._run(self._Resp(404, "<html><body><main>gone</main></body></html>"))


class HuaweiClosedDetectionTest(unittest.TestCase):
    """华为撤岗只能逐岗判，且必须「宁可漏判不可错杀」。

    2026-07-29：接口对任何 jobId 都返 HTTP 200 + 109 字段骨架，区别在有没有填内容——
    在招岗 ~32 个字段有值且 jobname 非空；不存在的 jobId 只有 5 个字段有值、jobname 空。
    本源刚因「列表缺席即撤岗」的误判差点被清库（460 个 active 逐个核验下来全在招），
    故判死必须两个条件同时成立，接口返半截数据时一律不判死。
    """

    class _Resp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            if self._payload is None:
                raise ValueError("not json")
            return self._payload

    URL = ("https://career.huawei.com/reccampportal/portal5/"
           "social-recruitment-detail.html?jobId=30153&dataSource=1")

    def _run(self, resp):
        orig = enrich.httpx.get
        enrich.httpx.get = lambda *a, **k: resp
        try:
            return enrich._detail_huawei({"jd_url": self.URL}, {})
        finally:
            enrich.httpx.get = orig

    def _live_payload(self):
        p = {f"f{i}": f"v{i}" for i in range(30)}
        p.update({"jobname": "法务专员", "mainBusiness": "1、负责签约授权管理"})
        return p

    def test_live_job_returns_body_not_closed(self):
        self.assertEqual(self._run(self._Resp(self._live_payload())), "1、负责签约授权管理")

    def test_empty_skeleton_is_closed(self):
        payload = {f"f{i}": None for i in range(105)}
        payload.update({"jobname": "", "appFlag": "N", "appStatus": 0})
        with self.assertRaises(enrich.JobClosedError):
            self._run(self._Resp(payload))

    def test_half_filled_payload_is_never_closed(self):
        """接口抽风返半截数据（jobname 空但字段填了不少）→ 绝不判死，宁可漏判。"""
        payload = {f"f{i}": f"v{i}" for i in range(25)}
        payload["jobname"] = ""
        self.assertEqual(self._run(self._Resp(payload)), "")

    def test_unparseable_response_is_not_closed(self):
        self.assertEqual(self._run(self._Resp(None)), "")

    def test_registered_as_httpx_detail(self):
        self.assertEqual(enrich.detail_class("huawei"), "httpx")
