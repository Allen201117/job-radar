import os
import sys
from unittest import mock
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[3] / "crawler")
sys.path.insert(0, ROOT)

from adapters.base import RawJob
from adapters.mihoyo import MihoyoAdapter
from robots import _parse_robots
import run


print("[robots wildcard]", _parse_robots(
    "User-agent: *\nDisallow: /*.pdf$\n", "/jobs/cv.pdf"))


class Response:
    def __init__(self, page):
        self.page = page
    def raise_for_status(self):
        if self.page == 2:
            raise RuntimeError("synthetic page-2 failure")
    def json(self):
        return {"data": {"total": 200, "list": [
            {"id": f"job-{i}"} for i in range(100)
        ]}}


class Client:
    def post(self, url, json):
        return Response(json["pageNo"])


try:
    MihoyoAdapter()._fetch_board(Client(), 0, "social")
except Exception as exc:
    print("[later-page failure] raised after page 1:", repr(exc))


class BaseReviewAdapter:
    name = "_review"
    supports_absence_liveness = True
    regions = []
    def should_skip(self, _url):
        return None


class PartialAdapter(BaseReviewAdapter):
    def fetch(self, _url):
        self.reported_total = 10
        self.fetch_complete = False
        return "partial"
    def parse(self, _payload):
        return [RawJob(company="ReviewCo", title="Engineer", location="上海",
                       summary="valid summary", jd_url="https://example.test/jobs/1")]


class EmptyAdapter(BaseReviewAdapter):
    def fetch(self, _url):
        self.reported_total = 0
        self.fetch_complete = True
        return "empty"
    def parse(self, _payload):
        return []


updates = []
sweeps = []


def update_run(_db, _run_id, status, **kwargs):
    updates.append((status, kwargs))


def normalize(raw, source_id, company, regions):
    return {"source_id": source_id, "company": company, "title": raw.title,
            "location": raw.location, "summary": raw.summary,
            "jd_url": raw.jd_url}


common = {
    "check_robots": mock.Mock(return_value={"allowed": True, "reason": ""}),
    "db.create_crawl_run": mock.Mock(return_value="run-1"),
    "db.update_crawl_run": update_run,
    "db.update_source_timestamp": mock.Mock(),
    "normalizer.validate_job_quality": mock.Mock(return_value=(True, "")),
    "normalizer.normalize": normalize,
    "cap_summary_for_storage": lambda x: x,
    "jobs_db.enabled": mock.Mock(return_value=True),
    "jobs_db._now": mock.Mock(return_value="cutoff"),
    "_get_thread_jobs_conn": mock.Mock(return_value=object()),
    "jobs_db.upsert_jobs_batch": mock.Mock(return_value=(1, 0)),
    "jobs_db.sweep_absent_jobs": lambda *a, **kw: (
        sweeps.append((a, kw)) or {"candidates": 0, "active": 0, "expired": 0, "action": "none"}),
}


def run_case(adapter):
    source = {"id": "source-1", "company": "ReviewCo", "adapter_name": "_review",
              "source_url": "https://example.test/jobs", "regions": []}
    with mock.patch.dict(run.ADAPTERS, {"_review": adapter}), mock.patch.multiple(
            run, check_robots=common["check_robots"],
            cap_summary_for_storage=common["cap_summary_for_storage"],
            _get_thread_jobs_conn=common["_get_thread_jobs_conn"]), \
         mock.patch.object(run.db, "create_crawl_run", common["db.create_crawl_run"]), \
         mock.patch.object(run.db, "update_crawl_run", common["db.update_crawl_run"]), \
         mock.patch.object(run.db, "update_source_timestamp", common["db.update_source_timestamp"]), \
         mock.patch.object(run.normalizer, "validate_job_quality", common["normalizer.validate_job_quality"]), \
         mock.patch.object(run.normalizer, "normalize", common["normalizer.normalize"]), \
         mock.patch.object(run.jobs_db, "enabled", common["jobs_db.enabled"]), \
         mock.patch.object(run.jobs_db, "_now", common["jobs_db._now"]), \
         mock.patch.object(run.jobs_db, "upsert_jobs_batch", common["jobs_db.upsert_jobs_batch"]), \
         mock.patch.object(run.jobs_db, "sweep_absent_jobs", common["jobs_db.sweep_absent_jobs"]):
        return run._process_one_source(source, object())


updates.clear()
partial_result = run_case(PartialAdapter())
print("[partial coverage status] result=", partial_result,
      "recorded=", updates[-1] if updates else None)

updates.clear()
sweeps.clear()
empty_result = run_case(EmptyAdapter())
print("[complete empty absence] result=", empty_result,
      "sweep_calls=", len(sweeps), "recorded=", updates[-1] if updates else None)
