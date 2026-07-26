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
                fingerprinter=lambda _url: {
                    "platform": "greenhouse",
                    "adapter": "greenhouse",
                    "source_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
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
        self.assertEqual(sb.writes, [])
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
        result, _used, _inserted = gf.process_company(
            _entry(),
            supabase=_Sb(),
            jobs_conn=_Conn(),
            apply=False,
            search_remaining=2,
            insert_allowed=True,
            now=NOW,
            fingerprinter=lambda _url: {
                "platform": "iguopin",
                "adapter": "iguopin",
                "source_url": None,
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


if __name__ == "__main__":
    unittest.main()
