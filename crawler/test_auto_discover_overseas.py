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
    """回归守卫：2026-09-19 探活验证通过的候选 (Epic Games / Flexport 的 greenhouse board url)
    source_url 恰好已在库，被 plan_inserts 的 URL 去重当场丢弃。主线程复核线上库确认那两行
    实际是 enabled=false（停用源）——给停用源补 regions 没有意义（不会被抓，产出仍是 0），
    所以只对 enabled=true 且 crawl_method='http' 的行生效；enabled=false 的单独计
    skipped_disabled，不更新也不静默吞掉。"""

    def _cand(self, company="Flexport", url="https://boards-api.greenhouse.io/v1/boards/flexport/jobs"):
        return {"company": company, "adapter": "greenhouse", "url": url,
                "industry": "物流", "_valid": 26, "regions": ["US", "SG", "Remote"]}

    def _row(self, **overrides):
        row = {"id": "src-1", "source_url": "https://boards-api.greenhouse.io/v1/boards/flexport/jobs",
               "regions": ["CN"], "enabled": True, "crawl_method": "http"}
        row.update(overrides)
        return row

    def test_expands_regions_for_enabled_http_url_already_in_library(self):
        sb = _UpdateSb()
        url_rows = {self._row()["source_url"]: self._row()}
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 1)
        self.assertEqual(skipped_disabled, 0)
        self.assertEqual(remaining, [])
        self.assertEqual(len(sb.updates), 1)
        eq_id, payload = sb.updates[0]
        self.assertEqual(eq_id, "src-1")
        self.assertEqual(sorted(payload["regions"]), ["CN", "Remote", "SG", "US"])

    def test_disabled_source_is_not_updated_and_counted_separately(self):
        # 主线程实测：Epic Games/Flexport 那两行 enabled=false——补 regions 不会让它产出岗位，
        # 只会掩盖「这源为什么被停用」这个更该被看到的问题，所以不更新、单独计数上报。
        sb = _UpdateSb()
        url_rows = {self._row()["source_url"]: self._row(enabled=False)}
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 0)
        self.assertEqual(skipped_disabled, 1)
        self.assertEqual(len(remaining), 1, "停用源候选交还 remaining，不静默吞掉")
        self.assertEqual(sb.updates, [], "停用源不许被 UPDATE")

    def test_non_http_crawl_method_is_not_updated(self):
        # 浏览器源（playwright）现状是否健康未知，本函数只做轻量 UPDATE，不做浏览器验证 → 不碰。
        sb = _UpdateSb()
        url_rows = {self._row()["source_url"]: self._row(crawl_method="playwright")}
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 0)
        self.assertEqual(skipped_disabled, 0, "浏览器源不算「停用」，不计入 skipped_disabled")
        self.assertEqual(len(remaining), 1, "浏览器源候选原样交还，沿用旧行为（被 URL 去重挡掉）")
        self.assertEqual(sb.updates, [], "浏览器源不许被本函数 UPDATE")

    def test_dry_run_does_not_write(self):
        sb = _UpdateSb()
        url_rows = {self._row()["source_url"]: self._row()}
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], url_rows, apply=False)
        self.assertEqual(expanded, 0, "dry-run 不许真的 update")
        self.assertEqual(skipped_disabled, 0)
        self.assertEqual(remaining, [])
        self.assertEqual(sb.updates, [])

    def test_new_url_passes_through_untouched(self):
        sb = _UpdateSb()
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], {}, apply=True)
        self.assertEqual(expanded, 0)
        self.assertEqual(skipped_disabled, 0)
        self.assertEqual(len(remaining), 1, "url 不在库时应原样交回，走正常 plan_inserts 路径")
        self.assertEqual(sb.updates, [])

    def test_already_fully_covered_is_not_double_counted_as_expansion(self):
        sb = _UpdateSb()
        url_rows = {self._row()["source_url"]: self._row(regions=["CN", "US", "SG", "Remote"])}
        expanded, skipped_disabled, remaining = ado.expand_existing_regions(
            sb, [self._cand()], url_rows, apply=True)
        self.assertEqual(expanded, 0, "regions 已全覆盖不是「补漏」，不能算扩源产出")
        self.assertEqual(skipped_disabled, 0)
        self.assertEqual(len(remaining), 1, "交还给真去重路径处理，不在这里悄悄吞掉")
        self.assertEqual(sb.updates, [])


class FetchUrlRegionRowsTest(unittest.TestCase):
    def test_indexes_by_source_url_and_skips_blank(self):
        rows = [
            {"id": "1", "source_url": "https://x/1", "regions": ["CN"], "enabled": True, "crawl_method": "http"},
            {"id": "2", "source_url": "  ", "regions": ["CN"], "enabled": True, "crawl_method": "http"},
            {"id": "3", "source_url": "https://x/3", "regions": None, "enabled": False, "crawl_method": "playwright"},
        ]
        with mock.patch.object(ado.db, "fetch_all_rows", return_value=rows):
            out = ado.fetch_url_region_rows(mock.Mock())
        self.assertEqual(set(out.keys()), {"https://x/1", "https://x/3"})
        self.assertEqual(out["https://x/1"]["id"], "1")
        self.assertEqual(out["https://x/3"]["enabled"], False)


if __name__ == "__main__":
    unittest.main()
