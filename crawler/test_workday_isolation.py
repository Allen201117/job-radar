import json
import unittest

import run
from adapters.workday import WorkdayAdapter


class WorkdayHostIsolationTest(unittest.TestCase):
    def setUp(self):
        self.captured = []
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
        run.db.update_source_timestamp = lambda sb, sid: None
        run.check_robots = lambda url: {"allowed": True, "reason": ""}
        run.jobs_db.enabled = lambda: False

        def capture(_sb, jobs):
            self.captured.extend(jobs)
            return (len(jobs), 0)

        run.db.upsert_jobs_batch = capture

    def tearDown(self):
        run.db.create_crawl_run = self._orig["create"]
        run.db.update_crawl_run = self._orig["update"]
        run.db.upsert_jobs_batch = self._orig["upsert_batch"]
        run.db.update_source_timestamp = self._orig["ts"]
        run.check_robots = self._orig["robots"]
        run.jobs_db.enabled = self._orig["jobs_enabled"]
        run.ADAPTERS.pop("_workday_isolation", None)

    def test_per_source_workday_host_state_is_not_clobbered(self):
        class _InterleavingWorkday(WorkdayAdapter):
            interleaved = False

            def fetch(self, source_url):
                self._parse_endpoint(source_url)
                if not type(self).interleaved:
                    type(self).interleaved = True
                    run._process_one_source({
                        "adapter_name": "_workday_isolation",
                        "company": "Workday B",
                        "source_url": "https://b-tenant.wd5.myworkdayjobs.com/wday/cxs/b/SiteB/jobs",
                        "id": "source-b",
                    }, supabase=None)
                return json.dumps({
                    "_host": self._host,
                    "_site": self._site,
                    "trusted_posts": [{
                        "title": "Software Engineer",
                        "externalPath": "/job/Shanghai-China/Software-Engineer_JR1",
                    }],
                    "text_posts": [],
                })

        run.ADAPTERS["_workday_isolation"] = _InterleavingWorkday()
        run._process_one_source({
            "adapter_name": "_workday_isolation",
            "company": "Workday A",
            "source_url": "https://a-tenant.wd5.myworkdayjobs.com/wday/cxs/a/SiteA/jobs",
            "id": "source-a",
        }, supabase=None)

        by_source = {job["source_id"]: job["jd_url"] for job in self.captured}
        self.assertIn("a-tenant.wd5.myworkdayjobs.com", by_source.get("source-a", ""))
        self.assertIn("b-tenant.wd5.myworkdayjobs.com", by_source.get("source-b", ""))


if __name__ == "__main__":
    unittest.main()
