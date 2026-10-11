"""建画像之前先认别名（2026-10-11：136 家公司各有 2~5 个画像，根因是每个入口只按正名去重）。

钉四件事：① 归属与网站侧共用夹具逐条一致；② ensure_profile 先找后建；
③ 按源名补画像、单公司取画像都不再给别名另建一个；④ crawler/ 里没有第四处直接 upsert 画像。
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

import bu_extract
import company_profile_resolve as R
import insight_backlog as B

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "profile-resolve-cases.json").read_text(encoding="utf-8")
)


class FakeQuery:
    def __init__(self, sb):
        self.sb, self.op, self.payload, self.filters = sb, "select", None, {}

    def select(self, *a, **k):
        return self

    def eq(self, col, value):
        self.filters[col] = value
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def upsert(self, payload, **k):
        self.op, self.payload = "upsert", payload
        return self

    def execute(self):
        rows = self.sb.rows
        if self.op == "update":
            self.sb.calls.append(("update", dict(self.filters), self.payload))
            return type("R", (), {"data": []})()
        if self.op == "upsert":
            self.sb.calls.append(("upsert", self.payload))
            batch = self.payload if isinstance(self.payload, list) else [self.payload]
            for row in batch:
                rows.append({"id": f"new-{len(rows)}", "aliases": [], **row})
            return type("R", (), {"data": []})()
        data = [r for r in rows if all(r.get(c) == v for c, v in self.filters.items())]
        if hasattr(self, "window"):
            data = data[self.window[0]:self.window[1] + 1]
        return type("R", (), {"data": data})()


class FakeSB:
    def __init__(self, rows):
        self.rows, self.calls = [dict(r) for r in rows], []

    def table(self, name):
        assert name in ("company_profiles", "sources"), name
        return FakeQuery(self) if name == "company_profiles" else _SourcesQuery(self)


class _SourcesQuery(FakeQuery):
    def execute(self):
        data = self.sb.sources
        if hasattr(self, "window"):
            data = data[self.window[0]:self.window[1] + 1]
        return type("R", (), {"data": data})()


PROFILES = [
    {"id": "p1", "company": "知乎", "aliases": ["知乎 Zhihu"]},
    {"id": "p2", "company": "腾讯音乐", "aliases": ["腾讯音乐 TME"]},
    {"id": "p3", "company": "万达集团", "aliases": []},
]


class SharedFixtureTest(unittest.TestCase):
    def test_resolution_matches_the_shared_fixture(self):
        index = bu_extract.build_profile_index(FIXTURE["profiles"])
        for case in FIXTURE["cases"]:
            got = R.resolve(case["name"], index)
            self.assertEqual(got["id"] if got else None, case["expect"], f"{case['name']!r}：{case['why']}")


class EnsureProfileTest(unittest.TestCase):
    def test_alias_returns_the_existing_profile_without_creating(self):
        sb = FakeSB(PROFILES)
        got = R.ensure_profile(sb, "知乎 Zhihu")
        self.assertEqual(got["id"], "p1")
        self.assertEqual(sb.calls, [])

    def test_normalized_name_returns_the_existing_profile(self):
        sb = FakeSB(PROFILES)
        self.assertEqual(R.ensure_profile(sb, "万达控股集团")["id"], "p3")
        self.assertEqual(sb.calls, [])

    def test_unknown_name_is_created_once(self):
        sb = FakeSB(PROFILES)
        got = R.ensure_profile(sb, " 新公司 ")
        self.assertEqual(got["company"], "新公司")
        self.assertEqual(sb.calls, [("upsert", {"company": "新公司"})])

    def test_requeue_touches_the_canonical_profile_not_a_new_row(self):
        sb = FakeSB(PROFILES)
        R.ensure_profile(sb, "腾讯音乐 TME", requeue=True)
        self.assertEqual(sb.calls, [("update", {"id": "p2"}, {"insight_checked_at": None})])

    def test_requeue_on_unknown_name_creates_it_queued(self):
        sb = FakeSB(PROFILES)
        R.ensure_profile(sb, "新公司", requeue=True)
        self.assertEqual(sb.calls, [("upsert", {"company": "新公司", "insight_checked_at": None})])

    def test_empty_name_never_creates(self):
        sb = FakeSB(PROFILES)
        self.assertIsNone(R.ensure_profile(sb, "  "))
        self.assertEqual(sb.calls, [])


class CallersTest(unittest.TestCase):
    def test_seed_from_sources_skips_names_that_are_aliases(self):
        sb = FakeSB(PROFILES)
        sb.sources = [{"company": "知乎 Zhihu"}, {"company": "腾讯音乐"}, {"company": "万达控股集团"},
                      {"company": "真的新公司"}]
        created = B.seed_from_sources(sb)
        self.assertEqual(created, 1)
        self.assertEqual(sb.calls, [("upsert", [{"company": "真的新公司"}])])

    def test_seed_from_sources_builds_one_profile_for_a_new_company_with_channel_sources(self):
        """同一批里「X」「X 校招」「X 实习」都是新的：只建「X」。三个都建，这家公司当场又是三个画像。"""
        sb = FakeSB(PROFILES)
        sb.sources = [{"company": "新来的公司 校招"}, {"company": "新来的公司"}, {"company": "新来的公司 实习"}]
        self.assertEqual(B.seed_from_sources(sb), 1)
        self.assertEqual(sb.calls, [("upsert", [{"company": "新来的公司"}])])

    def test_channel_suffixed_source_name_resolves_to_the_existing_profile(self):
        sb = FakeSB(PROFILES)
        sb.sources = [{"company": "知乎 校招"}, {"company": "腾讯音乐 实习"}]
        self.assertEqual(B.seed_from_sources(sb), 0)
        self.assertEqual(sb.calls, [])

    def test_fetch_one_company_returns_the_canonical_profile_for_a_list_name(self):
        """必投清单写「腾讯音乐 TME」的另一个叫法时，校招周期链路拿到的是已有画像，不是新建的空画像。"""
        sb = FakeSB(PROFILES)
        got = B.fetch_one_company(sb, "腾讯音乐 TME")
        self.assertEqual((got["id"], got["company"]), ("p2", "腾讯音乐"))
        self.assertEqual(sb.calls, [])


class DownstreamOfAliasResolutionTest(unittest.TestCase):
    """名字按别名归到画像之后，下游凡是「拿清单名 / 岗位公司名去比画像正名」的地方都要跟着认别名。"""

    def test_covered_names_include_aliases_and_resolved_list_names(self):
        """清单写「中通」、时间线挂在画像「中通快递」上：只比正名的话「中通」每轮都被重新挑中，白花搜索额度。"""
        import campus_cycle_backlog as C

        profiles = [
            {"id": "zto", "company": "中通快递", "aliases": ["中通"]},
            {"id": "wd", "company": "万达集团", "aliases": []},
            {"id": "jd", "company": "京东", "aliases": []},
        ]
        verified = [{"company_id": "zto"}, {"company_id": "wd"}]
        with mock.patch.object(C.db, "fetch_all_rows", side_effect=[verified, profiles]):
            covered = C.fetch_covered_company_names(FakeSB([]), ["中通", "万达控股集团", "京东", "没有画像的公司"])
        self.assertEqual(covered, {"中通快递", "中通", "万达集团", "万达控股集团"})
        targets = C.select_cycle_targets(
            {"物流": [{"name": "中通"}], "地产": [{"name": "万达控股集团"}], "互联网": [{"name": "京东"}]},
            covered, cap=10)
        self.assertEqual([t["company"] for t in targets], ["京东"])

    def test_t3_queue_counts_jobs_posted_under_an_alias(self):
        """画像叫「知乎」、岗位公司名是「知乎 Zhihu」：排队时要把这些岗算给它，否则有岗的公司排到队尾。"""
        rows = [
            {"id": "a", "company": "没岗的公司", "aliases": [], "t3_fail_count": 0},
            {"id": "b", "company": "知乎", "aliases": ["知乎 Zhihu"], "t3_fail_count": 0},
        ]
        seen = {}

        def fake_counts(conn, sql, params):
            seen["names"] = sorted(params[1])
            return [{"company": "知乎 Zhihu", "active_count": 53, "demand_count": 0}]

        def fake_rows(factory, *a, **k):
            return list(rows) if not seen.get("first") and not seen.update(first=True) else []

        with mock.patch.object(B.db, "fetch_all_rows", side_effect=fake_rows),              mock.patch.object(B.jobs_db, "enabled", return_value=True),              mock.patch.object(B.jobs_db, "get_conn", return_value=mock.MagicMock()),              mock.patch.object(B.jobs_db, "fetch_all", side_effect=fake_counts),              mock.patch.object(B.must_apply, "all_names", return_value=[]):
            queue = B.fetch_t3_queue(FakeSB([]), limit=0)
        self.assertEqual(seen["names"], ["没岗的公司", "知乎", "知乎 Zhihu"])
        self.assertEqual([r["company"] for r in queue], ["知乎", "没岗的公司"])


class SingleEntryContractTest(unittest.TestCase):
    def test_only_resolver_aware_code_upserts_profiles(self):
        """crawler/ 里直接 upsert company_profiles 的只许这三处，且都先过归属：
        company_profile_resolve（公共入口）、insight_backlog.seed_from_sources（批量，先用索引筛过）、
        bu_extract.create_profiles（只给归属不到任何画像的岗位公司名建）。"""
        root = Path(__file__).resolve().parent
        pattern = re.compile(r"table\(\s*[\"']company_profiles[\"']\s*\)\s*\.(?:upsert|insert)\(", re.S)
        offenders = sorted(
            p.name for p in root.glob("*.py")
            if not p.name.startswith("test_") and pattern.search(p.read_text(encoding="utf-8"))
        )
        self.assertEqual(offenders, ["bu_extract.py", "company_profile_resolve.py", "insight_backlog.py"])
        seed = B.seed_from_sources.__code__.co_names
        self.assertIn("company_profile_resolve", seed)


if __name__ == "__main__":
    unittest.main()
