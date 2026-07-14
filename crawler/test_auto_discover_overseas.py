"""海外必投 ATS 扩源单测：不打真实网络、不连数据库。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_discover_overseas as ado


def _target(company="Stripe", slugs=None, ats=None):
    return {
        "company": company, "cn": company, "industry": "互联网/科技",
        "slugs": slugs or [company.lower()],
        "ats": ats or ["greenhouse", "lever"],
    }


class OverseasTargetsTest(unittest.TestCase):
    def test_load_targets_marks_every_entry_must_apply(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "targets.json"
            path.write_text(json.dumps([_target("Stripe"), _target("Grab")]), encoding="utf-8")
            with mock.patch.object(ado, "TARGETS_JSON", path):
                out = ado.load_targets()
        self.assertEqual([row["company"] for row in out], ["Stripe", "Grab"])
        self.assertTrue(all(row.get("_must_apply") for row in out))

    def test_build_candidates_expands_slug_and_ats_combinations(self):
        out = ado.build_candidates([_target(slugs=["stripe", "stripe-inc"], ats=["greenhouse", "lever"])])
        self.assertEqual(len(out), 4)
        self.assertEqual({row["adapter"] for row in out}, {"greenhouse", "lever"})
        self.assertTrue(all(row["company"] == "Stripe" for row in out))


class OverseasProbeTest(unittest.TestCase):
    def test_confirm_candidates_drops_probe_failures(self):
        cands = ado.build_candidates([_target("Stripe", ats=["greenhouse"]), _target("Grab", ats=["lever"])])
        def probe_fn(cand):
            if cand["company"] == "Stripe":
                return {"parsed": 3, "valid": 2, "sample": "https://jobs.example/1"}
            return {"parsed": 2, "valid": 0, "sample": "https://jobs.example/2"}

        out = ado.confirm_candidates(cands, timeout=1, probe_fn=probe_fn)
        self.assertEqual([row["company"] for row in out], ["Stripe"])
        self.assertEqual(out[0]["regions"], ["US", "SG", "Remote"])

    def test_confirm_requires_parsed_jobs_and_detail_link(self):
        cands = ado.build_candidates([_target(ats=["greenhouse", "lever"])])
        replies = iter([
            {"parsed": 0, "valid": 2, "sample": "https://jobs.example/1"},
            {"parsed": 2, "valid": 2, "sample": ""},
        ])
        self.assertEqual(ado.confirm_candidates(cands, timeout=1, probe_fn=lambda _: next(replies)), [])


class OverseasPlanningTest(unittest.TestCase):
    def test_reuses_must_apply_tier_before_other_targets(self):
        curated = [
            _target("Other"),
            {**_target("MustApply"), "_must_apply": True},
        ]
        out = ado.ad.plan_targets(curated, set(), set(), cap=10, seed=1)
        self.assertEqual([row["company"] for row in out], ["MustApply", "Other"])

    def test_insert_cap_is_enforced_after_url_dedup(self):
        passed = [
            {"company": f"C{i}", "adapter": "lever", "url": f"https://api.lever.co/{i}",
             "regions": ["US", "SG", "Remote"]}
            for i in range(5)
        ]
        out = ado.ad.plan_inserts(passed, set(), cap=2)
        self.assertEqual(len(out), 2)
        self.assertTrue(all(row["regions"] == ["US", "SG", "Remote"] for row in out))


class _InsertQuery:
    def __init__(self, sb, name):
        self.sb = sb
        self.name = name

    def insert(self, payload):
        self.sb.inserts[self.name] = payload
        return self

    def upsert(self, payload, **_):
        self.sb.inserts[self.name] = payload
        return self

    def execute(self):
        class Result:
            data = [{"id": "source-1"}]
        return Result()


class _InsertSb:
    def __init__(self):
        self.inserts = {}

    def table(self, name):
        return _InsertQuery(self, name)


class OverseasInsertTest(unittest.TestCase):
    def test_insert_source_persists_overseas_regions(self):
        sb = _InsertSb()
        row = {"company": "Stripe", "adapter": "greenhouse", "url": "https://jobs.example",
               "industry": "互联网/科技", "_valid": 2, "regions": ["US", "SG", "Remote"]}
        with mock.patch.object(ado.ad, "resolve_watch_requests"):
            ado.ad.insert_source(sb, row)
        self.assertEqual(sb.inserts["sources"]["regions"], ["US", "SG", "Remote"])


if __name__ == "__main__":
    unittest.main()
