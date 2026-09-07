#!/usr/bin/env python3
"""Read-only lifecycle counterexamples using real producer functions and fake I/O.

Assertions reproduce defects at application baseline 1154512; they are not fixes.
No environment files, real network requests, or database connections are used.
"""
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "crawler"))
import insight_backlog as B
import bu_signals as S


class Query:
    def __init__(self, sb, name):
        self.sb, self.name = sb, name
        self.op, self.payload, self.filters = "select", None, []

    def select(self, *_args):
        return self

    def insert(self, row):
        self.op, self.payload = "insert", deepcopy(row)
        return self

    def update(self, row):
        self.op, self.payload = "update", deepcopy(row)
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def lt(self, key, value):
        self.filters.append(("lt", key, value))
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        if self.name == self.sb.fail_table and self.op == "insert":
            raise RuntimeError("synthetic source insertion failure")
        if self.op != "select":
            self.sb.writes.append((self.name, self.op, self.payload, self.filters))
        return SimpleNamespace(data=self.sb.existing if self.op == "select" else [])


class Store:
    def __init__(self, existing=None, fail_table=None):
        self.existing, self.fail_table = existing or [], fail_table
        self.writes = []

    def table(self, name):
        return Query(self, name)


PROFILE = {"id": "company-test", "company": "示例公司", "aliases": []}
CLAIM = {"content": "示例讨论内容", "grade": "experience", "sample_size": 12,
         "quote": "only source A says this", "time_window": "2026 年"}
SOURCES = [{"url": "https://example.com/a", "publisher": "A", "snippet": "A excerpt"},
           {"url": "https://example.org/b", "publisher": "B", "snippet": "B excerpt"}]
JUDGE = {"verdict": "entailed", "confidence": 0.95}


def source_failure():
    sb = Store(fail_table="insight_sources")
    try:
        B.write_experience(sb, PROFILE["id"], CLAIM, SOURCES, JUDGE, "active")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected injected source failure")
    assert len(sb.writes) == 1 and sb.writes[0][2]["status"] == "active"


def changed_listing_keeps_old_sources():
    sb = Store(existing=[{"id": "old-listing"}])
    B.write_listing(sb, PROFILE["id"], {
        "title": "new official title", "content": "new official content", "payload": {},
        "origin": "official", "source_url": "https://example.org/new-official-source",
    })
    assert len(sb.writes) == 1 and sb.writes[0][0] == "insight_items"
    assert sb.writes[0][2]["origin"] == "official"


def copied_excerpt_and_duplicate_identity():
    sb = Store()
    for _ in range(2):
        B.write_experience(sb, PROFILE["id"], CLAIM, SOURCES, JUDGE, "active")
    items = [row for name, _, row, _ in sb.writes if name == "insight_items"]
    sources = [row for name, _, row, _ in sb.writes if name == "insight_sources"]
    assert len(items) == 2 and items[0]["id"] != items[1]["id"]
    assert all(row["excerpt"] == CLAIM["quote"] for row in sources)


def failed_t2_is_checked():
    sb = Store()
    with patch.object(B.wikidata, "get_company_facts", side_effect=TimeoutError("synthetic")):
        assert B.enrich_company(sb, PROFILE) == "noface"
    assert "insight_checked_at" in sb.writes[0][2]
    assert "insight_fail_count" not in sb.writes[0][2]


def exhausted_t3_is_checked():
    sb = Store()
    with patch.object(B._ROUTER, "remaining_above_reserve", return_value=10), \
         patch.object(B.llm_budget, "remaining", return_value=0), \
         patch.object(B._ROUTER, "search", side_effect=AssertionError("search must not run")):
        assert B.enrich_company_t3(sb, PROFILE) == "empty"
    assert any("t3_checked_at" in row for _, _, row, _ in sb.writes)


def partial_topic_retires_every_topic():
    sb = Store()
    packs = [{"query": "{c} 加班", "topic": "加班文化", "dimension": "culture"},
             {"query": "{c} 面试", "topic": "面试难度", "dimension": "path"}]
    entry = {"status": "active", "claim": CLAIM, "judge": JUDGE}
    with ExitStack() as stack:
        for obj, name, value in [(B, "T3_QUERY_PACK", packs)]:
            stack.enter_context(patch.object(obj, name, value))
        stack.enter_context(patch.object(B._ROUTER, "remaining_above_reserve", return_value=10))
        stack.enter_context(patch.object(B.llm_budget, "remaining", return_value=10))
        stack.enter_context(patch.object(B.E, "llm_usage_totals", return_value={"calls": 0}))
        stack.enter_context(patch.object(B._ROUTER, "search", side_effect=[SOURCES, RuntimeError("second topic failed")]))
        stack.enter_context(patch.object(B, "filter_t3_results", return_value=(SOURCES, 0)))
        stack.enter_context(patch.object(B.E, "run_pipeline", return_value=[entry]))
        stack.enter_context(patch.object(B, "_pick_sources", return_value=SOURCES))
        stack.enter_context(patch.object(B.E, "consensus_ok", return_value=True))
        stack.enter_context(patch.object(B.topic_gate, "gate_new_claim", return_value=("keep", "overtime", "culture")))
        assert B.enrich_company_t3(sb, PROFILE) == "wrote"
    retire = [w for w in sb.writes if w[0] == "insight_items" and w[1] == "update"]
    assert len(retire) == 1 and retire[0][2] == {"status": "retired"}
    keys = {key for _, key, _ in retire[0][3]}
    assert keys == {"company_id", "origin", "status", "last_verified_at"}, keys


def retired_signal_reactivated():
    subject = {"id": "subject-test", "name": "示例业务线", "status": "retired"}
    metric = {"dimension": "hiring", "content": "观测值", "sample_size": 20, "payload": {},
              "metric_key": "test_metric", "metric_value": 20, "metric_unit": "jobs",
              "scope": "示例范围", "time_window": "2026 年"}
    old = {"id": "retired-item", "metric_key": "test_metric", "status": "retired"}
    rows, _ = S.plan_subject_rows(subject, PROFILE["id"], [metric], [old], "2026-09-07T00:00:00Z", 7)
    assert rows[0]["id"] == old["id"] and rows[0]["status"] == "active"


with ExitStack() as guards:
    guards.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
    guards.enter_context(patch.object(B.db, "get_supabase", side_effect=AssertionError("real DB forbidden")))
    guards.enter_context(patch.object(B.db, "load_environment", side_effect=AssertionError("env files forbidden")))
    for case in (source_failure, changed_listing_keeps_old_sources, copied_excerpt_and_duplicate_identity,
                 failed_t2_is_checked, exhausted_t3_is_checked, partial_topic_retires_every_topic,
                 retired_signal_reactivated):
        with redirect_stdout(StringIO()):
            case()
        print("REPRODUCED", case.__name__)
