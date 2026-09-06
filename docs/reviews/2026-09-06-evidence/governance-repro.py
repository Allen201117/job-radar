#!/usr/bin/env python3
"""Job Radar governance review reproductions.

Loads the repository's real functions and mocks network/DB/browser dependencies.
Does not read environment files or credentials and performs no repository/DB writes.

Run from the repository root:
  python3 docs/reviews/2026-09-06-evidence/governance-repro.py
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
from unittest import mock
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[3])
CRAWLER = os.path.join(REPO, "crawler")
sys.path.insert(0, CRAWLER)

import audit_dead_links as audit  # noqa: E402
import enrich_backlog as backlog  # noqa: E402
import jobs_db  # noqa: E402


class TextPage:
    def __init__(self, text):
        self.text = text

    def inner_text(self, *_args, **_kwargs):
        return self.text


def repro_broad_dead_marker():
    verdict = audit.classify(
        TextPage("软件工程师 职位编号 404123，负责推荐系统研发，欢迎投递。"),
        "软件工程师",
    )
    assert verdict == ("dead", "404"), verdict
    print("PASS broad marker: live-looking body containing job number 404123 =>", verdict)


class FakeSupabaseUpdate:
    def __init__(self):
        self.patches = []
        self.current = None

    def table(self, *_args):
        return self

    def update(self, patch):
        self.current = patch
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        self.patches.append(self.current)
        return None


def repro_http_empty_becomes_alive():
    sb = FakeSupabaseUpdate()
    row = {"id": "J", "title": "T", "summary": "existing JD", "enrich_fail_count": 0}
    src = {"adapter_name": "amazon"}
    with mock.patch.object(backlog.enrich, "enrich_one", return_value=""):
        result = backlog.enrich_row(sb, row, src)
    assert result == "alive", result
    assert list(sb.patches[0]) == ["enrich_checked_at"], sb.patches
    print("PASS tri-state collapse: semantic empty + existing summary =>", result, sb.patches[0])


class FakePage(TextPage):
    def goto(self, *_args, **_kwargs):
        return None

    def reload(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, *_args, **_kwargs):
        return None


class FakeBrowser:
    def __init__(self, page):
        self.page = page

    def new_context(self, **_kwargs):
        return self

    def new_page(self):
        return self.page

    def close(self):
        return None


class FakeChromium:
    def __init__(self, page):
        self.page = page

    def launch(self, **_kwargs):
        return FakeBrowser(self.page)


class FakePlaywrightContext:
    def __init__(self, page):
        self.value = type("PW", (), {"chromium": FakeChromium(page)})()

    def __enter__(self):
        return self.value

    def __exit__(self, *_args):
        return False


def repro_browser_unknown_gets_checked_stamp():
    # >40 chars, no title and no dead marker => suspect, which is not an alive confirmation.
    page = FakePage("Access denied by upstream security policy; request id abcdefghijklmnopqrstuvwxyz.")
    writes = []
    sample = [{"id": "00000000-0000-0000-0000-000000000001", "title": "软件工程师",
               "company": "X", "jd_url": "https://example.com/job/1"}]
    old_argv = sys.argv[:]
    sys.argv = ["audit_dead_links.py", "--apply", "--limit", "1"]
    try:
        with mock.patch.object(audit.db, "get_supabase", return_value=object()), \
             mock.patch.object(audit.jobs_db, "enabled", return_value=True), \
             mock.patch.object(audit.jobs_db, "get_conn", return_value=object()), \
             mock.patch.object(audit.jobs_db, "execute", side_effect=lambda _c, sql, vals: writes.append((sql, vals))), \
             mock.patch.object(audit, "fetch_browser_liveness", return_value=sample), \
             mock.patch.object(audit, "sync_playwright", return_value=FakePlaywrightContext(page)), \
             mock.patch.object(audit.ops_runs, "record_ops_run", return_value=None), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            audit.main()
    finally:
        sys.argv = old_argv
    assert len(writes) == 1, writes
    sql, vals = writes[0]
    assert "enrich_checked_at = %s" in sql and "status" not in sql, (sql, vals)
    print("PASS browser unknown stamp: suspect navigation wrote", sql)


class FakeCursor:
    def __init__(self):
        self.calls = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        if sql.startswith("select id, status from jobs where canonical_jd_url"):
            self.rows = []  # expired row and its event were purged; no tombstone remains

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self):
        self.cur = FakeCursor()

    def cursor(self):
        return self.cur


def repro_purge_then_reinsert():
    purge_text = open(os.path.join(REPO, ".github/workflows/purge-expired.yml"), encoding="utf-8").read()
    assert "delete from jobs where status = 'expired'" in purge_text.lower()
    conn = FakeConn()
    job = {
        "source_id": "00000000-0000-0000-0000-000000000001",
        "company": "X",
        "title": "T",
        "location": "L",
        "jd_url": "https://example.com/jobs/closed-1",
        "summary": "stale list payload",
    }
    with mock.patch.object(jobs_db, "_annotate_recruitment", side_effect=lambda _jobs: None):
        result = jobs_db.upsert_job(conn, job)
    statements = [sql for sql, _ in conn.cur.calls]
    assert result == "created", result
    assert any(sql.startswith("insert into jobs") for sql in statements), statements
    print("PASS purge resurrection: same canonical after deleted row =>", result, "with fresh INSERT")


def show_schedule_gap():
    # cron 2,10,22 produces 8h,12h,4h gaps; one matrix job may run 5.5h.
    gaps = [8, 12, 4]
    assert min(gaps) < 330 / 60
    print("PASS overlap window: cron gaps", gaps, "hours; job timeout", 330 / 60, "hours")


if __name__ == "__main__":
    repro_broad_dead_marker()
    repro_http_empty_becomes_alive()
    repro_browser_unknown_gets_checked_stamp()
    repro_purge_then_reinsert()
    show_schedule_gap()
    print("All governance reproductions passed.")
