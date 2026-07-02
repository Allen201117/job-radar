import unittest

import run
from adapters.base import RawJob


class _RegionCapturingAdapter:
    seen_regions = []

    def should_skip(self, url):
        return None

    def fetch(self, url):
        return "<html>ok</html>"

    def parse(self, html):
        type(self).seen_regions.append(getattr(self, "regions", None))
        return [RawJob(
            company="Region Test",
            title="Software Engineer",
            location="Singapore",
            job_type=None,
            summary="Build reliable backend services.",
            jd_url="https://example.com/jobs/region-test",
            apply_url="https://example.com/jobs/region-test",
            posted_at=None,
        )]


class TestRunRegions(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "create": run.db.create_crawl_run,
            "update": run.db.update_crawl_run,
            "upsert_batch": run.db.upsert_jobs_batch,
            "ts": run.db.update_source_timestamp,
            "robots": run.check_robots,
            "jobs_enabled": run.jobs_db.enabled,
        }
        run.db.create_crawl_run = lambda sb, sid: "run-1"
        run.db.update_crawl_run = lambda *a, **k: None
        run.db.upsert_jobs_batch = lambda sb, jobs: (len(jobs), 0)
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}
        run.jobs_db.enabled = lambda: False
        run.ADAPTERS["_region_capture"] = _RegionCapturingAdapter()
        _RegionCapturingAdapter.seen_regions = []

    def tearDown(self):
        run.db.create_crawl_run = self._orig["create"]
        run.db.update_crawl_run = self._orig["update"]
        run.db.upsert_jobs_batch = self._orig["upsert_batch"]
        run.db.update_source_timestamp = self._orig["ts"]
        run.check_robots = self._orig["robots"]
        run.jobs_db.enabled = self._orig["jobs_enabled"]
        run.ADAPTERS.pop("_region_capture", None)

    def _source(self, **overrides):
        source = {
            "adapter_name": "_region_capture",
            "company": "Region Test",
            "source_url": "https://example.com/jobs",
            "id": "source-1",
        }
        source.update(overrides)
        return source

    def test_default_regions_cn(self):
        result = run._process_one_source(self._source(), supabase=None)

        self.assertEqual(result["status"], "success")
        self.assertEqual(_RegionCapturingAdapter.seen_regions, [{"CN"}])

    def test_regions_passthrough(self):
        result = run._process_one_source(self._source(regions=["US", "SG"]), supabase=None)

        self.assertEqual(result["status"], "success")
        self.assertEqual(_RegionCapturingAdapter.seen_regions, [{"US", "SG"}])


if __name__ == "__main__":
    unittest.main()
