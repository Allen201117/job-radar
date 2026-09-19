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


class _UpdateQuery:
    def __init__(self, sb, name):
        self.sb = sb
        self.name = name
        self._eq = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, _col, value):
        self._eq = value
        return self

    def execute(self):
        self.sb.updates.append((self._eq, self._payload))
        class Result:
            data = [{}]
        return Result()


class _UpdateSb:
    def __init__(self):
        self.updates = []

    def table(self, name):
        return _UpdateQuery(self, name)


class ExpandExistingRegionsTest(unittest.TestCase):
    """回归守卫：2026-09-19 实测 overseas 道连续 22 天 produced=0——探活真验证通过的候选
    (Epic Games / Flexport 的 greenhouse board url) 恰好已在库（国内 regions={CN}），被
    plan_inserts 的 URL 去重当场丢弃，一天一天地把真探到的产出吃掉。expand_existing_regions
    改成给这类候选补 regions，不再白白丢弃。"""

    def _cand(self, company="Flexport", url="https://boards-api.greenhouse.io/v1/boards/flexport/jobs"):
        return {"company": company, "adapter": "greenhouse", "url": url,
                "industry": "物流", "_valid": 26, "regions": ["US", "SG", "Remote"]}

    def test_expands_regions_for_url_already_in_library(self):
        sb = _UpdateSb()
        url_rows = {"https://boards-api.greenhouse.io/v1/boards/flexport/jobs":
                    {"id": "src-1", "source_url": "https://boards-api.greenhouse.io/v1/boards/flexport/jobs",
                     "regions": ["CN"]}}
        expanded, remaining = ado.expand_existing_regions(sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 1)
        self.assertEqual(remaining, [])
        self.assertEqual(len(sb.updates), 1)
        eq_id, payload = sb.updates[0]
        self.assertEqual(eq_id, "src-1")
        self.assertEqual(sorted(payload["regions"]), ["CN", "Remote", "SG", "US"])

    def test_dry_run_does_not_write(self):
        sb = _UpdateSb()
        url_rows = {"https://boards-api.greenhouse.io/v1/boards/flexport/jobs":
                    {"id": "src-1", "regions": ["CN"]}}
        expanded, remaining = ado.expand_existing_regions(sb, [self._cand()], url_rows, apply=False)
        self.assertEqual(expanded, 0, "dry-run 不许真的 update")
        self.assertEqual(remaining, [])
        self.assertEqual(sb.updates, [])

    def test_new_url_passes_through_untouched(self):
        sb = _UpdateSb()
        expanded, remaining = ado.expand_existing_regions(sb, [self._cand()], {}, apply=True)
        self.assertEqual(expanded, 0)
        self.assertEqual(len(remaining), 1, "url 不在库时应原样交回，走正常 plan_inserts 路径")
        self.assertEqual(sb.updates, [])

    def test_already_fully_covered_is_not_double_counted_as_expansion(self):
        sb = _UpdateSb()
        url_rows = {"https://boards-api.greenhouse.io/v1/boards/flexport/jobs":
                    {"id": "src-1", "regions": ["CN", "US", "SG", "Remote"]}}
        expanded, remaining = ado.expand_existing_regions(sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 0, "regions 已全覆盖不是「补漏」，不能算扩源产出")
        self.assertEqual(len(remaining), 1, "交还给真去重路径处理，不在这里悄悄吞掉")
        self.assertEqual(sb.updates, [])


class FetchUrlRegionRowsTest(unittest.TestCase):
    def test_indexes_by_source_url_and_skips_blank(self):
        rows = [
            {"id": "1", "source_url": "https://x/1", "regions": ["CN"]},
            {"id": "2", "source_url": "  ", "regions": ["CN"]},
            {"id": "3", "source_url": "https://x/3", "regions": None},
        ]
        with mock.patch.object(ado.db, "fetch_all_rows", return_value=rows):
            out = ado.fetch_url_region_rows(mock.Mock())
        self.assertEqual(set(out.keys()), {"https://x/1", "https://x/3"})
        self.assertEqual(out["https://x/1"]["id"], "1")


if __name__ == "__main__":
    unittest.main()
