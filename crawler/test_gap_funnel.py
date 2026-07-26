import contextlib
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gap_funnel as gf


NOW = datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc)


class _Response:
    def __init__(self, data=None):
        self.data = data or []


class _Query:
    def __init__(self, sb, name):
        self.sb = sb
        self.name = name
        self.action = None
        self.payload = None
        self.filters = []

    def select(self, *_args):
        self.action = "select"
        return self

    def insert(self, payload):
        self.action, self.payload = "insert", dict(payload)
        return self

    def upsert(self, payload, on_conflict=None):
        # 台账走 upsert。假件必须实现它：早先没实现时 _write_attempt 会抛 AttributeError
        # 被 run_round 的 try/except 吞掉，于是「dry-run 没写任何东西」的断言是假通过。
        self.action = "upsert"
        self.payload = payload if isinstance(payload, list) else dict(payload)
        self.on_conflict = on_conflict
        return self

    def update(self, payload):
        self.action, self.payload = "update", dict(payload)
        return self

    def delete(self):
        self.action = "delete"
        return self

    def eq(self, *args):
        self.filters.append(args)
        return self

    def limit(self, _value):
        return self

    def execute(self):
        if self.action == "select":
            rows = list(self.sb.source_rows if self.name == "sources" else [])
            for column, value in self.filters:
                rows = [row for row in rows if row.get(column) == value]
            return _Response(rows)
        self.sb.writes.append((self.name, self.action, self.payload))
        if self.name == "sources" and self.action == "insert":
            row = {**self.payload, "id": "source-new"}
            self.sb.source_rows.append(row)
            return _Response([row])
        return _Response([])


class _Sb:
    def __init__(self, source_rows=None):
        self.writes = []
        self.source_rows = list(source_rows or [])

    def table(self, name):
        return _Query(self, name)


class _Conn:
    def __init__(self):
        self.executed = []


def _entry():
    return {
        "company": "甲公司",
        "pattern": "%甲公司%",
        "industries": ["金融"],
        "official_entry_url": "https://jobs.acme.com",
        "detected_platform": "greenhouse",
    }


class AcceptanceGateTest(unittest.TestCase):
    def _run(self, counts, jd_ok=True, apply=True):
        sb = _Sb()
        conn = _Conn()
        process_calls = []

        def process_source(source, supplied_sb):
            process_calls.append((dict(source), supplied_sb))
            return {"status": "success", "created": counts[1], "updated": 0}

        result = gf.run_acceptance_gate(
            _entry(),
            adapter="greenhouse",
            source_url="https://boards.greenhouse.io/acme",
            supabase=sb,
            jobs_conn=conn,
            apply=apply,
            process_source=process_source,
            read_counts=lambda _conn, _sid: {"healthy": counts[0], "total": counts[1]},
            read_samples=lambda _conn, _sid: [{
                "company": "甲公司", "title": "工程师",
                "jd_url": "https://jobs/acme/1",
            }],
            validate_jd=lambda _url, _title, _company: jd_ok,
            delete_jobs=lambda c, sid: c.executed.append(("delete_jobs", sid)),
            now=NOW,
        )
        return result, sb, conn, process_calls

    def test_healthy_enables_source(self):
        result, sb, conn, calls = self._run((1, 2))
        self.assertEqual(result["state"], "healthy")
        self.assertTrue(result["kept_source"])
        self.assertTrue(result["evidence"]["source_inserted_new"])
        self.assertEqual(len(calls), 1)
        self.assertIn(("sources", "update", {"enabled": True, "notes": "gap_funnel:healthy"}), sb.writes)
        self.assertEqual(conn.executed, [])

    def test_thin_only_enables_source_for_enrichment(self):
        result, sb, conn, _ = self._run((0, 2))
        self.assertEqual(result["state"], "thin_only")
        self.assertTrue(result["kept_source"])
        self.assertIsNotNone(result["next_retry_at"])
        self.assertIn(("sources", "update", {"enabled": True, "notes": "gap_funnel:thin_only"}), sb.writes)
        self.assertEqual(conn.executed, [])

    def test_browser_gate_writes_playwright_source_and_rejects_thin_only(self):
        sb = _Sb()
        conn = _Conn()
        result = gf.run_acceptance_gate(
            _entry(),
            adapter="company_spa",
            source_url="https://jobs.example.com",
            supabase=sb,
            jobs_conn=conn,
            apply=True,
            crawl_method="playwright",
            enable_thin=False,
            process_source=lambda _source, _sb: {"status": "success"},
            read_counts=lambda _conn, _sid: {"healthy": 0, "total": 2},
            read_samples=lambda _conn, _sid: [{
                "company": "甲公司",
                "title": "工程师",
                "jd_url": "https://jobs.example.com/1",
            }],
            validate_jd=lambda _url, _title, _company: True,
            delete_jobs=lambda c, sid: c.executed.append(("delete_jobs", sid)),
            now=NOW,
        )
        inserted = next(
            payload
            for name, action, payload in sb.writes
            if name == "sources" and action == "insert"
        )
        self.assertEqual(inserted["crawl_method"], "playwright")
        self.assertEqual(result["state"], "thin_only")
        self.assertFalse(result["kept_source"])
        self.assertIn(("delete_jobs", "source-new"), conn.executed)

    def test_zero_jobs_rolls_back_source_and_jobs(self):
        result, sb, conn, _ = self._run((0, 0))
        self.assertEqual(result["state"], "no_active_jobs")
        self.assertFalse(result["kept_source"])
        self.assertIn(("delete_jobs", "source-new"), conn.executed)
        self.assertTrue(any(name == "crawl_runs" and action == "delete" for name, action, _ in sb.writes))
        self.assertTrue(any(name == "sources" and action == "delete" for name, action, _ in sb.writes))

    def test_failed_jd_validation_rolls_back(self):
        result, sb, conn, _ = self._run((1, 1), jd_ok=False)
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertIn(("delete_jobs", "source-new"), conn.executed)
        self.assertTrue(any(name == "sources" and action == "delete" for name, action, _ in sb.writes))

    def test_dry_run_performs_no_write_or_crawl(self):
        result, sb, conn, calls = self._run((1, 1), apply=False)
        self.assertEqual(result["state"], "dry_run")
        self.assertEqual(sb.writes, [])
        self.assertEqual(conn.executed, [])
        self.assertEqual(calls, [])

    def test_reuses_disabled_source_url_instead_of_inserting_duplicate(self):
        sb = _Sb([{
            "id": "source-old",
            "company": "旧称",
            "source_url": "https://boards.greenhouse.io/acme",
            "adapter_name": "greenhouse",
            "enabled": False,
        }])
        conn = _Conn()
        calls = []
        result = gf.run_acceptance_gate(
            _entry(),
            adapter="greenhouse",
            source_url="https://boards.greenhouse.io/acme",
            supabase=sb,
            jobs_conn=conn,
            apply=True,
            process_source=lambda source, _sb: calls.append(dict(source)) or {
                "status": "success", "created": 1, "updated": 0
            },
            read_counts=lambda _conn, _sid: {"healthy": 1, "total": 1},
            read_samples=lambda _conn, _sid: [
                {
                    "company": "甲公司", "title": "工程师",
                    "jd_url": "https://jobs/acme/1",
                }
            ],
            validate_jd=lambda _url, _title, _company: True,
            now=NOW,
        )
        self.assertEqual(result["state"], "healthy")
        self.assertFalse(result["evidence"]["source_inserted_new"])
        self.assertEqual(calls[0]["id"], "source-old")
        self.assertFalse(any(name == "sources" and action == "insert" for name, action, _ in sb.writes))

    def test_failed_reused_source_restores_its_previous_metadata(self):
        old = {
            "id": "source-old",
            "company": "旧公司",
            "source_url": "https://boards.greenhouse.io/acme",
            "source_type": "official",
            "adapter_name": "greenhouse",
            "crawl_method": "http",
            "industry": "旧行业",
            "enabled": False,
            "notes": "人工停用",
        }
        sb = _Sb([old])
        conn = _Conn()
        result = gf.run_acceptance_gate(
            _entry(),
            adapter="company_spa",
            source_url=old["source_url"],
            supabase=sb,
            jobs_conn=conn,
            apply=True,
            crawl_method="playwright",
            process_source=lambda _source, _sb: {"status": "success"},
            read_counts=lambda _conn, _sid: {"healthy": 0, "total": 0},
            delete_jobs=lambda c, sid: c.executed.append(("delete_jobs", sid)),
            now=NOW,
        )
        self.assertEqual(result["state"], "no_active_jobs")
        restored = [
            payload
            for name, action, payload in sb.writes
            if name == "sources" and action == "update" and payload.get("notes") == "人工停用"
        ]
        self.assertEqual(restored, [{key: old[key] for key in old if key != "id"}])
        self.assertIn(("delete_jobs", "source-old"), conn.executed)

    def test_wrong_company_jobs_fail_the_acceptance_gate(self):
        sb = _Sb()
        result = gf.run_acceptance_gate(
            _entry(),
            adapter="greenhouse",
            source_url="https://boards.greenhouse.io/acme",
            supabase=sb,
            jobs_conn=_Conn(),
            apply=True,
            process_source=lambda _source, _sb: {"status": "success"},
            read_counts=lambda _conn, _sid: {"healthy": 1, "total": 1},
            read_samples=lambda _conn, _sid: [{
                "company": "乙公司", "title": "工程师",
                "jd_url": "https://jobs/acme/1",
            }],
            validate_jd=lambda _url, _title, _company: True,
            delete_jobs=lambda _conn, _sid: None,
            now=NOW,
        )
        self.assertEqual(result["state"], "no_stable_jd")
        self.assertFalse(result["kept_source"])

    def test_jd_page_requires_title_and_company_identity(self):
        response = type("Response", (), {
            "status_code": 200,
            "text": "<h1>工程师</h1><div>乙公司招聘</div>",
        })()
        client = type("Client", (), {
            "get": lambda _self, _url, timeout: response,
        })()
        self.assertFalse(
            gf.validate_jd_url(
                "https://jobs/acme/1", "工程师", "甲公司", client=client
            )
        )

    def test_exception_after_insert_still_cleans_jobs_runs_and_source(self):
        sb = _Sb()
        conn = _Conn()
        with self.assertRaisesRegex(RuntimeError, "readback failed"):
            gf.run_acceptance_gate(
                _entry(),
                adapter="greenhouse",
                source_url="https://boards.greenhouse.io/acme",
                supabase=sb,
                jobs_conn=conn,
                apply=True,
                process_source=lambda _source, _sb: {"status": "success"},
                read_counts=lambda _conn, _sid: (_ for _ in ()).throw(
                    RuntimeError("readback failed")
                ),
                delete_jobs=lambda c, sid: c.executed.append(("delete_jobs", sid)),
                now=NOW,
            )
        self.assertIn(("delete_jobs", "source-new"), conn.executed)
        self.assertTrue(any(name == "crawl_runs" and action == "delete" for name, action, _ in sb.writes))
        self.assertTrue(any(name == "sources" and action == "delete" for name, action, _ in sb.writes))

    def test_rollback_failure_reports_original_and_cleanup_errors(self):
        sb = _Sb()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaisesRegex(
            RuntimeError, "readback failed.*delete failed"
        ):
            gf.run_acceptance_gate(
                _entry(),
                adapter="greenhouse",
                source_url="https://boards.greenhouse.io/acme",
                supabase=sb,
                jobs_conn=_Conn(),
                apply=True,
                process_source=lambda _source, _sb: {"status": "success"},
                read_counts=lambda _conn, _sid: (_ for _ in ()).throw(
                    RuntimeError("readback failed")
                ),
                delete_jobs=lambda _conn, _sid: (_ for _ in ()).throw(
                    RuntimeError("delete failed")
                ),
                now=NOW,
            )
        self.assertIn("RuntimeError: readback failed", output.getvalue())
        self.assertIn("RuntimeError: delete failed", output.getvalue())


class RoundCapTest(unittest.TestCase):
    def test_search_cap_stops_before_unsearched_company(self):
        queued = {
            "company": "甲公司",
            "pattern": "%甲公司%",
            "industries": ["金融"],
            "state": "unknown",
        }
        with mock.patch.dict("os.environ", {"GAP_FUNNEL_SEARCH_CAP": "0"}, clear=False), \
             mock.patch.object(
                 gf.gap_census,
                 "census",
                 return_value={"queue": [queued], "rows": [queued], "industry_coverage": {}},
             ), \
             mock.patch.object(gf, "process_company") as process:
            result = gf.run_round(
                scope="domestic",
                limit=1,
                apply=False,
                supabase=object(),
                jobs_conn=object(),
                now=NOW,
            )
        process.assert_not_called()
        self.assertEqual(result["outcomes"], [])

    def test_dry_run_consumes_search_usage_but_writes_nothing(self):
        provider = mock.Mock()
        provider.name = "qianfan"
        provider.is_configured.return_value = True
        provider.remaining.return_value = 10
        provider.search.return_value = [{
            "url": "https://acme.mokahr.com/social-recruitment/acme/1"
        }]
        router = type("Router", (), {"providers": [provider]})()
        sb = _Sb()
        conn = _Conn()
        queued = {
            **_entry(),
            "official_entry_url": None,
            "state": "unknown",
        }
        real_process_company = gf.process_company

        def finder(company, supplied_sb, **kwargs):
            return gf.entry_finder.find_official_entry(
                company, supplied_sb, router=router, **kwargs
            )

        def process(row, **kwargs):
            return real_process_company(
                row,
                **kwargs,
                finder=finder,
                fingerprinter=lambda _url, **_kwargs: {
                    "platform": "greenhouse",
                    "adapter": "greenhouse",
                    "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                    "identity_ok": True,
                    "identity_reason": "page_company_match:甲公司",
                },
                prober=lambda _candidate: {"ok": True, "valid": 1},
            )

        output = io.StringIO()
        with mock.patch.object(
            gf.gap_census,
            "census",
            return_value={"queue": [queued], "rows": [queued], "industry_coverage": {}},
        ), mock.patch.object(gf, "process_company", side_effect=process), \
             contextlib.redirect_stdout(output):
            result = gf.run_round(
                scope="domestic",
                limit=1,
                apply=False,
                supabase=sb,
                jobs_conn=conn,
                now=NOW,
            )

        provider.consume.assert_called_once_with(sb, 1)
        self.assertEqual(result["metrics"]["search_used"], 1)
        self.assertIn("真实搜索消耗=1/", output.getvalue())
        # dry-run 契约：**台账要写**（它是我们自己的簿记，不写就等于这轮搜索白烧、下轮重搜），
        # 但 sources / jobs 一个字都不许动。
        written_tables = {name for name, _action, _payload in sb.writes}
        self.assertEqual(written_tables, {"must_apply_gap_attempts"})
        attempt = [p for name, action, p in sb.writes
                   if name == "must_apply_gap_attempts" and action == "upsert"][0]
        self.assertEqual(attempt["state"], "platform_known",
                         "dry-run 查到的入口要落成 platform_known，下轮才能跳过搜索直接复用")
        self.assertEqual(attempt["official_entry_url"],
                         "https://acme.mokahr.com/social-recruitment/acme/1")
        self.assertNotIn("sources", written_tables)
        self.assertEqual(conn.executed, [])

    def test_company_exception_is_printed_before_attempt_write(self):
        queued = {
            "company": "甲公司",
            "pattern": "%甲公司%",
            "industries": ["金融"],
            "state": "unknown",
        }
        output = io.StringIO()
        with mock.patch.object(
            gf.gap_census,
            "census",
            return_value={"queue": [queued], "rows": [queued], "industry_coverage": {}},
        ), mock.patch.object(
            gf, "process_company", side_effect=ValueError("坏入口")
        ), contextlib.redirect_stdout(output):
            result = gf.run_round(
                scope="domestic",
                limit=1,
                apply=False,
                supabase=_Sb(),
                jobs_conn=_Conn(),
                now=NOW,
            )

        self.assertIn(
            "[gap_funnel] 甲公司 处理异常: ValueError: 坏入口",
            output.getvalue(),
        )
        self.assertEqual(result["outcomes"][0]["fail_reason"], "ValueError: 坏入口")

    def test_iguopin_entry_uses_must_apply_company_as_search_keyword(self):
        probed = []
        row = {
            **_entry(),
            "official_entry_url": "https://www.iguopin.com/job?company=甲公司",
        }
        result, _used, _inserted = gf.process_company(
            row,
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            fingerprinter=lambda _url, **_kwargs: {
                "platform": "iguopin",
                "adapter": "iguopin",
                "source_url": None,
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            },
            prober=lambda candidate: probed.append(candidate) or {
                "ok": True, "valid": 1
            },
        )
        self.assertEqual(result["state"], "platform_known")
        self.assertEqual(
            probed[0]["url"],
            "https://www.iguopin.com/job?company=%E7%94%B2%E5%85%AC%E5%8F%B8",
        )

    def test_candidate_identity_retry_uses_second_routable_candidate(self):
        urls = [
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
            "https://boards.greenhouse.io/acme",
        ]
        fingerprinted = []
        probed = []

        def finder(*_args, **_kwargs):
            return {
                "found": True,
                "official_entry_url": urls[0],
                "search_used": 1,
                "candidates": [
                    {"url": urls[0], "verdict": "trusted_ats", "score": 100},
                    {"url": urls[1], "verdict": "trusted_ats", "score": 100},
                ],
            }

        def fingerprinter(url, *, company):
            fingerprinted.append((url, company))
            if url == urls[0]:
                return {
                    "platform": "hotjob",
                    "adapter": "hotjob",
                    "source_url": urls[0],
                    "identity_ok": False,
                    "identity_reason": "page_company_not_found",
                }
            return {
                "platform": "greenhouse",
                "adapter": "greenhouse",
                "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            }

        row = {**_entry(), "official_entry_url": None}
        result, used, _inserted = gf.process_company(
            row,
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=finder,
            fingerprinter=fingerprinter,
            prober=lambda candidate: probed.append(candidate) or {
                "ok": True, "valid": 1
            },
        )
        self.assertEqual([url for url, _company in fingerprinted], urls)
        self.assertEqual(used, 1)
        self.assertEqual(result["state"], "platform_known")
        self.assertEqual(result["official_entry_url"], urls[1])
        self.assertEqual(len(probed), 1)
        self.assertEqual(probed[0]["adapter"], "greenhouse")

    def test_all_identity_mismatches_become_wrong_platform_with_rejected_hosts(self):
        urls = [
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
            "https://hire.feishu.cn/customer/zhongkechuangda",
        ]
        result, _used, _inserted = gf.process_company(
            {**_entry(), "official_entry_url": None},
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=lambda *_args, **_kwargs: {
                "found": True,
                "official_entry_url": urls[0],
                "search_used": 1,
                "candidates": [
                    {"url": url, "verdict": "trusted_ats", "score": 100}
                    for url in urls
                ],
            },
            fingerprinter=lambda url, **_kwargs: {
                "platform": "hotjob" if "hotjob" in url else "feishu",
                "adapter": "hotjob" if "hotjob" in url else "feishu",
                "source_url": url,
                "identity_ok": False,
                "identity_reason": "page_company_not_found",
            },
            prober=lambda _candidate: self.fail("身份不符的候选不应进入 probe"),
        )
        self.assertEqual(result["state"], "wrong_platform")
        self.assertEqual(result["fail_reason"], "候选入口均非本公司（张冠李戴）")
        self.assertIsNone(result["official_entry_url"])
        self.assertEqual(
            result["evidence"]["rejected_candidate_hosts"],
            ["gimc.hotjob.cn", "hire.feishu.cn"],
        )

    def test_incomplete_hotjob_url_never_reaches_probe(self):
        prober = mock.Mock()
        result, _used, _inserted = gf.process_company(
            {**_entry(), "official_entry_url": "https://gimc.hotjob.cn"},
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            fingerprinter=lambda _url, **_kwargs: {
                "platform": "hotjob",
                "adapter": "hotjob",
                "source_url": None,
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            },
            prober=prober,
        )
        prober.assert_not_called()
        self.assertEqual(result["state"], "wrong_platform")

    def test_httpx_lane_routes_browser_fallback_adapter_without_probing(self):
        prober = mock.Mock()
        result, _used, _inserted = gf.process_company(
            {
                **_entry(),
                "official_entry_url": "https://hire.feishu.cn/customer/acme",
            },
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            fingerprinter=lambda _url, **_kwargs: {
                "platform": "feishu",
                "adapter": "feishu",
                "source_url": "https://hire.feishu.cn/customer/acme",
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            },
            prober=prober,
        )
        prober.assert_not_called()
        self.assertEqual(result["state"], "wrong_platform")
        self.assertEqual(result["detected_platform"], "unknown_spa")

    def test_cached_blacklisted_url_is_discarded_and_search_runs_again(self):
        finder = mock.Mock(return_value={
            "found": True,
            "official_entry_url": "https://boards.greenhouse.io/acme",
            "search_used": 1,
            "candidates": [{
                "url": "https://boards.greenhouse.io/acme",
                "verdict": "trusted_ats",
                "score": 100,
            }],
            "evidence": {"candidate_urls": []},
        })
        result, used, _inserted = gf.process_company(
            {
                **_entry(),
                "official_entry_url": "https://m.nj.bendibao.com/job/179796.shtm",
            },
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=finder,
            fingerprinter=lambda _url, **_kwargs: {
                "platform": "greenhouse",
                "adapter": "greenhouse",
                "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            },
            prober=lambda _candidate: {"ok": True, "valid": 1},
        )
        finder.assert_called_once()
        self.assertEqual(used, 1)
        self.assertEqual(result["official_entry_url"], "https://boards.greenhouse.io/acme")
        self.assertIn(
            "m.nj.bendibao.com",
            result["evidence"]["rejected_candidate_hosts"],
        )

    def test_persisted_candidate_list_survives_into_next_round(self):
        urls = [
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
            "https://boards.greenhouse.io/acme",
        ]
        first, _used, _inserted = gf.process_company(
            {**_entry(), "official_entry_url": None},
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=lambda *_args, **_kwargs: {
                "found": True,
                "official_entry_url": urls[0],
                "search_used": 1,
                "candidates": [
                    {"url": url, "verdict": "trusted_ats", "score": 100}
                    for url in urls
                ],
                "evidence": {"candidate_urls": []},
            },
            fingerprinter=lambda _url, **_kwargs: {
                "platform": "hotjob",
                "adapter": "hotjob",
                "source_url": urls[0],
                "identity_ok": True,
                "identity_reason": "page_company_match:甲公司",
            },
            prober=lambda _candidate: {"ok": True, "valid": 1},
        )
        self.assertEqual(
            [item["url"] for item in first["evidence"]["candidate_urls"]],
            urls,
        )

        fingerprinted = []
        second, used, _inserted = gf.process_company(
            {
                **_entry(),
                "official_entry_url": first["official_entry_url"],
                "evidence": first["evidence"],
            },
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=lambda *_args, **_kwargs: self.fail("已有候选时不应重新搜索"),
            fingerprinter=lambda url, **_kwargs: (
                fingerprinted.append(url)
                or (
                    {
                        "platform": "hotjob",
                        "adapter": "hotjob",
                        "source_url": urls[0],
                        "identity_ok": False,
                        "identity_reason": "page_company_not_found",
                    }
                    if url == urls[0]
                    else {
                        "platform": "greenhouse",
                        "adapter": "greenhouse",
                        "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
                        "identity_ok": True,
                        "identity_reason": "page_company_match:甲公司",
                    }
                )
            ),
            prober=lambda _candidate: {"ok": True, "valid": 1},
        )
        self.assertEqual(fingerprinted, urls)
        self.assertEqual(used, 0)
        self.assertEqual(second["official_entry_url"], urls[1])

    def test_unverifiable_fallback_prevents_false_all_identity_mismatch(self):
        urls = [
            "https://jobs.example.com/careers",
            "https://gimc.hotjob.cn/GIMC/pb/social.html",
        ]
        result, _used, _inserted = gf.process_company(
            {**_entry(), "official_entry_url": None},
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=lambda *_args, **_kwargs: {
                "found": True,
                "official_entry_url": urls[0],
                "search_used": 1,
                "candidates": [{"url": url, "verdict": "likely_official", "score": 55}
                               for url in urls],
            },
            fingerprinter=lambda url, **_kwargs: (
                {
                    "platform": "anti_bot",
                    "adapter": None,
                    "source_url": url,
                    "reason": "anti_bot",
                    "identity_ok": False,
                    "identity_reason": "identity_unverifiable:anti_bot",
                }
                if url == urls[0]
                else {
                    "platform": "hotjob",
                    "adapter": "hotjob",
                    "source_url": urls[1],
                    "identity_ok": False,
                    "identity_reason": "page_company_not_found",
                }
            ),
            prober=lambda _candidate: self.fail("候选未通过身份门"),
        )
        self.assertEqual(result["state"], "anti_bot")
        self.assertNotEqual(result["fail_reason"], "候选入口均非本公司（张冠李戴）")

    def test_browser_fallback_beats_unroutable_httpx_candidate(self):
        urls = [
            "https://gimc.hotjob.cn",
            "https://hire.feishu.cn/customer/acme",
        ]
        result, _used, _inserted = gf.process_company(
            {**_entry(), "official_entry_url": None},
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            finder=lambda *_args, **_kwargs: {
                "found": True,
                "official_entry_url": urls[0],
                "search_used": 1,
                "candidates": [{"url": url, "verdict": "trusted_ats", "score": 100}
                               for url in urls],
            },
            fingerprinter=lambda url, **_kwargs: (
                {
                    "platform": "hotjob",
                    "adapter": "hotjob",
                    "source_url": None,
                    "identity_ok": True,
                    "identity_reason": "page_company_match:甲公司",
                }
                if url == urls[0]
                else {
                    "platform": "feishu",
                    "adapter": "feishu",
                    "source_url": urls[1],
                    "identity_ok": True,
                    "identity_reason": "page_company_match:甲公司",
                }
            ),
            prober=lambda _candidate: self.fail("浏览器候选不应进 httpx probe"),
        )
        self.assertEqual(result["detected_platform"], "unknown_spa")
        self.assertEqual(result["official_entry_url"], urls[1])


if __name__ == "__main__":
    unittest.main()
